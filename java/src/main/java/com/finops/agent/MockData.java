package com.finops.agent;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Canned AWS-shaped data used when MOCK_MODE=1.
 * Shapes mirror real SDK v2 response field names so the tools stay testable
 * without AWS credentials — mirrors src/mock_data.py in the Python edition.
 */
final class MockData {

    private MockData() {}

    static List<Map<String, Object>> rightsizingRecommendations() {
        return List.of(
            rec("i-0a1b2c3d4e5f67890", "web-server-prod-1", "m5.2xlarge",
                List.of(
                    metric("CPU", 12.3),
                    metric("MEMORY_USAGE", 18.7)
                ),
                List.of(option("m5.xlarge", 0.1, 140.16))),

            rec("i-0b2c3d4e5f678901a", "batch-worker-staging", "c5.2xlarge",
                List.of(metric("CPU", 22.5)),
                List.of(option("c5.large", 0.2, 186.15))),

            rec("i-0c3d4e5f6789012bc", "data-pipeline-worker", "r5.2xlarge",
                List.of(
                    metric("CPU", 8.1),
                    metric("MEMORY_USAGE", 31.0)
                ),
                List.of(option("r5.large", 0.15, 275.94)))
        );
    }

    static Map<String, Object> idleResources() {
        return Map.of(
            "unattached_volumes", List.of(
                vol("vol-0a1b2c3d4e5f67890", 100, "gp2", "2024-11-15T09:22:00Z", "old-db-snapshot-data"),
                vol("vol-0b2c3d4e5f6789012", 500, "gp3", "2024-09-03T14:07:00Z", null),
                vol("vol-0c3d4e5f678901234",  50, "gp2", "2025-01-20T08:45:00Z", "temp-test-volume")
            ),
            "unattached_eips", List.of(
                eip("eipalloc-0a1b2c3d4e5f67890", "54.201.100.25", "legacy-nat-ip"),
                eip("eipalloc-0b2c3d4e5f678901",  "52.87.200.42",  null)
            )
        );
    }

    // Monthly on-demand Linux prices for us-east-1 (730 hrs/month).
    // Source: https://aws.amazon.com/ec2/pricing/on-demand/ as of 2025-01.
    static final Map<String, Double> EC2_PRICES = Map.ofEntries(
        Map.entry("t3.micro",     7.59),
        Map.entry("t3.small",    15.18),
        Map.entry("t3.medium",   30.37),
        Map.entry("t3.large",    60.74),
        Map.entry("t3.xlarge",  121.47),
        Map.entry("t3.2xlarge", 242.94),
        Map.entry("m5.large",    70.08),
        Map.entry("m5.xlarge",  140.16),
        Map.entry("m5.2xlarge", 280.32),
        Map.entry("m5.4xlarge", 560.64),
        Map.entry("m5.8xlarge", 1121.28),
        Map.entry("c5.large",    62.05),
        Map.entry("c5.xlarge",  124.10),
        Map.entry("c5.2xlarge", 248.20),
        Map.entry("c5.4xlarge", 496.40),
        Map.entry("r5.large",    91.98),
        Map.entry("r5.xlarge",  183.96),
        Map.entry("r5.2xlarge", 367.92),
        Map.entry("r5.4xlarge", 735.84)
    );

    // ── private builders ─────────────────────────────────────────────────────

    private static Map<String, Object> rec(
            String instanceId, String name, String currentType,
            List<Map<String, Object>> metrics, List<Map<String, Object>> options) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("instanceArn", "arn:aws:ec2:us-east-1:123456789012:instance/" + instanceId);
        m.put("instanceName", name);
        m.put("currentInstanceType", currentType);
        m.put("finding", "OVER_PROVISIONED");
        m.put("utilizationMetrics", metrics);
        m.put("recommendationOptions", options);
        return m;
    }

    private static Map<String, Object> metric(String name, double value) {
        return Map.of("name", name, "statistic", "MAXIMUM", "value", value);
    }

    private static Map<String, Object> option(String instanceType, double risk, double savings) {
        return Map.of(
            "instanceType", instanceType,
            "performanceRisk", risk,
            "estimatedMonthlySavings", Map.of("value", savings, "currency", "USD")
        );
    }

    private static Map<String, Object> vol(String id, int sizeGib, String type,
                                            String createTime, String nameTag) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("VolumeId", id);
        m.put("Size", sizeGib);
        m.put("VolumeType", type);
        m.put("CreateTime", createTime);
        if (nameTag != null) m.put("Name", nameTag);
        return m;
    }

    private static Map<String, Object> eip(String allocId, String ip, String nameTag) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("AllocationId", allocId);
        m.put("PublicIp", ip);
        m.put("Domain", "vpc");
        if (nameTag != null) m.put("Name", nameTag);
        return m;
    }
}
