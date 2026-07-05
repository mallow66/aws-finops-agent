package com.finops.agent;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.computeoptimizer.ComputeOptimizerClient;
import software.amazon.awssdk.services.computeoptimizer.model.EstimatedMonthlySavings;
import software.amazon.awssdk.services.computeoptimizer.model.GetEc2InstanceRecommendationsRequest;
import software.amazon.awssdk.services.computeoptimizer.model.GetEc2InstanceRecommendationsResponse;
import software.amazon.awssdk.services.ec2.Ec2Client;
import software.amazon.awssdk.services.ec2.model.DescribeAddressesRequest;
import software.amazon.awssdk.services.ec2.model.DescribeVolumesRequest;
import software.amazon.awssdk.services.ec2.model.Filter;
import software.amazon.awssdk.services.pricing.PricingClient;
import software.amazon.awssdk.services.pricing.model.GetProductsRequest;
import software.amazon.awssdk.services.pricing.model.GetProductsResponse;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * The three FinOps tools.
 *
 * Design mirrors src/tools.py:
 *   - Package-private fetch*() methods hold all logic and are testable directly.
 *   - Public @Tool methods are one-liners that call fetch*() and serialize to JSON.
 *   - @Tool docstrings describe the interface for the LLM, not for humans.
 *   - MOCK_MODE=1 returns canned data; MOCK_MODE=0 calls real AWS SDK v2 clients.
 *
 * This class has no @Autowired fields, so it can be used both as a Spring bean
 * (agent mode) and as a plain `new FinOpsTools()` instance (tools-only mode).
 */
@Component
public class FinOpsTools {

    private static final boolean MOCK_MODE = "1".equals(System.getenv("MOCK_MODE"));
    private static final int HOURS_PER_MONTH = 730;

    private final ObjectMapper objectMapper = new ObjectMapper();

    // ── get_rightsizing_recommendations ──────────────────────────────────────

    @Tool(description = """
            Return EC2 rightsizing recommendations from AWS Compute Optimizer.
            Each record contains instanceArn, instanceName, currentInstanceType,
            finding (OVER_PROVISIONED | UNDER_PROVISIONED | OPTIMIZED),
            utilizationMetrics (CPU and memory max %), and recommendationOptions
            (list of alternatives with instanceType, performanceRisk 0-1, and
            estimatedMonthlySavings). The precomputed estimatedMonthlySavings is
            an approximation — call estimateInstanceCost on the current and
            recommended types to derive the exact saving from live pricing data.
            """)
    public String getRightsizingRecommendations() {
        return toJson(fetchRightsizingRecommendations());
    }

    List<Map<String, Object>> fetchRightsizingRecommendations() {
        if (MOCK_MODE) return MockData.rightsizingRecommendations();

        List<Map<String, Object>> result = new ArrayList<>();
        try (ComputeOptimizerClient client = ComputeOptimizerClient.create()) {
            String nextToken = null;
            do {
                var reqBuilder = GetEc2InstanceRecommendationsRequest.builder();
                if (nextToken != null) reqBuilder.nextToken(nextToken);
                GetEc2InstanceRecommendationsResponse resp =
                        client.getEC2InstanceRecommendations(reqBuilder.build());

                for (var rec : resp.instanceRecommendations()) {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("instanceArn", rec.instanceArn());
                    m.put("instanceName", rec.instanceName());
                    m.put("currentInstanceType", rec.currentInstanceType());
                    m.put("finding", rec.findingAsString());

                    m.put("utilizationMetrics", rec.utilizationMetrics().stream()
                        .map(metric -> Map.of(
                            "name",      metric.nameAsString(),
                            "statistic", metric.statisticAsString(),
                            "value",     metric.value()))
                        .collect(Collectors.toList()));

                    m.put("recommendationOptions", rec.recommendationOptions().stream()
                        .map(opt -> {
                            Map<String, Object> o = new LinkedHashMap<>();
                            o.put("instanceType",    opt.instanceType());
                            o.put("performanceRisk", opt.performanceRisk());
                            // Savings are nested: option → savingsOpportunity → estimatedMonthlySavings
                            if (opt.savingsOpportunity() != null) {
                                EstimatedMonthlySavings ems =
                                        opt.savingsOpportunity().estimatedMonthlySavings();
                                if (ems != null) {
                                    o.put("estimatedMonthlySavings", Map.of(
                                        "value",    ems.value(),
                                        "currency", ems.currencyAsString()));
                                }
                            }
                            return o;
                        })
                        .collect(Collectors.toList()));

                    result.add(m);
                }
                nextToken = resp.nextToken();
            } while (nextToken != null);
        }
        return result;
    }

    // ── get_idle_resources ───────────────────────────────────────────────────

    @Tool(description = """
            Return idle AWS resources that are incurring cost but not actively used.
            Scans for EBS volumes in 'available' state (never attached or detached)
            and Elastic IPs allocated in a VPC but not associated with any resource.
            Returns JSON with keys 'unattached_volumes' (VolumeId, Size GiB,
            VolumeType, CreateTime) and 'unattached_eips' (AllocationId, PublicIp).
            """)
    public String getIdleResources() {
        return toJson(fetchIdleResources());
    }

    Map<String, Object> fetchIdleResources() {
        if (MOCK_MODE) return MockData.idleResources();

        try (Ec2Client ec2 = Ec2Client.create()) {
            var volResp = ec2.describeVolumes(DescribeVolumesRequest.builder()
                .filters(Filter.builder().name("status").values("available").build())
                .build());

            List<Map<String, Object>> volumes = volResp.volumes().stream()
                .map(v -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("VolumeId",   v.volumeId());
                    m.put("Size",       v.size());
                    m.put("VolumeType", v.volumeTypeAsString());
                    m.put("CreateTime", v.createTime().toString());
                    return m;
                })
                .collect(Collectors.toList());

            var eipResp = ec2.describeAddresses(DescribeAddressesRequest.builder()
                .filters(Filter.builder().name("domain").values("vpc").build())
                .build());

            List<Map<String, Object>> eips = eipResp.addresses().stream()
                .filter(a -> a.associationId() == null)
                .map(a -> {
                    Map<String, Object> e = new LinkedHashMap<>();
                    e.put("AllocationId", a.allocationId());
                    e.put("PublicIp",     a.publicIp());
                    e.put("Domain",       a.domainAsString());
                    return e;
                })
                .collect(Collectors.toList());

            return Map.of("unattached_volumes", volumes, "unattached_eips", eips);
        }
    }

    // ── estimate_instance_cost ───────────────────────────────────────────────

    @Tool(description = """
            Look up the monthly on-demand Linux price of an EC2 instance type
            via the AWS Price List API.
            Use this after getRightsizingRecommendations to compute exact savings:
            call it once for the current instance type and once for the recommended
            type, then subtract to get the precise monthly saving instead of
            relying on the precomputed estimatedMonthlySavings figure.
            instanceType: EC2 instance type, e.g. 'm5.2xlarge', 'c5.large'.
            region: AWS region code, e.g. 'us-east-1'. Use 'us-east-1' if unknown.
            Returns JSON with instance_type, region, hourly_cost_usd, monthly_cost_usd,
            or an 'error' field if pricing data is unavailable for the requested type.
            """)
    public String estimateInstanceCost(String instanceType, String region) {
        return toJson(fetchInstanceCost(instanceType, region));
    }

    Map<String, Object> fetchInstanceCost(String instanceType, String region) {
        if (region == null || region.isBlank()) region = "us-east-1";

        if (MOCK_MODE) {
            Double price = MockData.EC2_PRICES.get(instanceType);
            if (price == null) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("instance_type",    instanceType);
                err.put("region",           region);
                err.put("monthly_cost_usd", null);
                err.put("error", "No mock price available for '" + instanceType
                        + "'. Known types: " + MockData.EC2_PRICES.keySet().stream().sorted().toList());
                return err;
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("instance_type",    instanceType);
            result.put("region",           region);
            result.put("hourly_cost_usd",  Math.round(price / HOURS_PER_MONTH * 1_000_000d) / 1_000_000d);
            result.put("monthly_cost_usd", Math.round(price * 100d) / 100d);
            return result;
        }

        // Pricing API is only available in us-east-1 / ap-south-1
        try (PricingClient pricing = PricingClient.builder().region(Region.US_EAST_1).build()) {
            GetProductsResponse resp = pricing.getProducts(GetProductsRequest.builder()
                .serviceCode("AmazonEC2")
                .filters(
                    pricingFilter("instanceType",    instanceType),
                    pricingFilter("operatingSystem", "Linux"),
                    pricingFilter("regionCode",      region),
                    pricingFilter("tenancy",         "Shared"),
                    pricingFilter("preInstalledSw",  "NA"),
                    pricingFilter("capacitystatus",  "Used"))
                .maxResults(1)
                .build());

            List<String> priceList = resp.priceList();
            if (priceList.isEmpty()) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("instance_type",    instanceType);
                err.put("region",           region);
                err.put("monthly_cost_usd", null);
                err.put("error", "No pricing data returned by AWS Price List API");
                return err;
            }

            // Parse the nested OnDemand pricing structure
            JsonNode item      = objectMapper.readTree(priceList.get(0));
            JsonNode onDemand  = item.get("terms").get("OnDemand");
            JsonNode offer     = onDemand.fields().next().getValue();
            JsonNode dimension = offer.get("priceDimensions").fields().next().getValue();
            double hourly      = Double.parseDouble(dimension.get("pricePerUnit").get("USD").asText());

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("instance_type",    instanceType);
            result.put("region",           region);
            result.put("hourly_cost_usd",  hourly);
            result.put("monthly_cost_usd", Math.round(hourly * HOURS_PER_MONTH * 100d) / 100d);
            return result;

        } catch (JsonProcessingException e) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("instance_type",    instanceType);
            err.put("region",           region);
            err.put("monthly_cost_usd", null);
            err.put("error", "Failed to parse pricing response: " + e.getMessage());
            return err;
        }
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    // Fully qualified to avoid import collision with software.amazon.awssdk.services.ec2.model.Filter
    private static software.amazon.awssdk.services.pricing.model.Filter pricingFilter(
            String field, String value) {
        return software.amazon.awssdk.services.pricing.model.Filter.builder()
                .type("TERM_MATCH")
                .field(field)
                .value(value)
                .build();
    }

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException e) {
            return "{\"error\":\"serialization failed: " + e.getMessage() + "\"}";
        }
    }
}
