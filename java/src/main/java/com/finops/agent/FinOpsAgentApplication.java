package com.finops.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeSet;

/**
 * AWS FinOps cost-optimization agent — Java / Spring AI edition.
 *
 * Run modes
 * ---------
 * --tools-only   Invoke each tool's fetch*() method directly; no LLM involved.
 *                Spring never starts, so no Bedrock credentials are needed.
 *                Works with MOCK_MODE=1 and no AWS access.
 * (default)      Start a Spring AI + Bedrock agent that calls the three @Tool
 *                methods autonomously and chains them to compute exact savings.
 */
@SpringBootApplication
public class FinOpsAgentApplication implements ApplicationRunner {

    private static final String DEFAULT_PROMPT = """
            Analyze our AWS spend. \
            Call getRightsizingRecommendations to find over-provisioned instances. \
            For each recommendation, call estimateInstanceCost on the current instance \
            type and on the recommended type, then compute the exact monthly saving \
            yourself instead of trusting the precomputed figure. \
            Also call getIdleResources and report unattached EBS volumes and Elastic IPs. \
            Finish with a prioritized summary and a total estimated monthly savings figure.\
            """;

    @Autowired
    private ChatClient.Builder chatClientBuilder;

    @Autowired
    private FinOpsTools finOpsTools;

    // ── entry point ──────────────────────────────────────────────────────────

    public static void main(String[] args) throws Exception {
        if (Arrays.stream(args).anyMatch("--tools-only"::equals)) {
            // Short-circuit before Spring starts — no Bedrock config needed.
            runToolsOnly();
            return;
        }
        SpringApplication.run(FinOpsAgentApplication.class, args);
    }

    // ── tools-only mode (static — runs without a Spring context) ─────────────

    private static void runToolsOnly() throws Exception {
        var tools  = new FinOpsTools();
        var mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);

        var recs = tools.fetchRightsizingRecommendations();
        printSection("Rightsizing Recommendations", recs, mapper);

        var idle = tools.fetchIdleResources();
        printSection("Idle Resources", idle, mapper);

        // Price every instance type mentioned in the recommendations.
        var types = new TreeSet<String>();
        for (var rec : recs) {
            types.add((String) rec.get("currentInstanceType"));
            @SuppressWarnings("unchecked")
            var options = (List<Map<String, Object>>) rec.get("recommendationOptions");
            if (options != null) options.forEach(o -> types.add((String) o.get("instanceType")));
        }
        types.removeIf(Objects::isNull);

        for (String itype : types) {
            printSection("Pricing: " + itype, tools.fetchInstanceCost(itype, "us-east-1"), mapper);
        }
    }

    private static void printSection(String title, Object data, ObjectMapper mapper) throws Exception {
        String bar = "=".repeat(62);
        System.out.println("\n" + bar);
        System.out.println("  " + title);
        System.out.println(bar);
        System.out.println(mapper.writeValueAsString(data));
    }

    // ── agent mode (Spring-managed) ──────────────────────────────────────────

    @Override
    public void run(ApplicationArguments args) {
        String prompt = args.getNonOptionArgs().isEmpty()
                ? DEFAULT_PROMPT
                : String.join(" ", args.getNonOptionArgs());

        String response = chatClientBuilder
                .defaultTools(finOpsTools)
                .build()
                .prompt()
                .user(prompt)
                .call()
                .content();

        System.out.println(response);
    }
}
