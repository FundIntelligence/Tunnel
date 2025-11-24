export interface ReportTemplate {
  id: string;
  name: string;
  description: string;
  fields: string[];
}

export const ReportTemplates: ReportTemplate[] = [
  {
    id: "performance",
    name: "Performance Report",
    description: "Portfolio returns & benchmark",
    fields: ["returns", "benchmark", "growthChart"]
  },
  {
    id: "annualFund",
    name: "Annual Fund Report",
    description: "Fund summary & asset allocation",
    fields: ["assetAllocation", "riskMetrics", "yearlyOverview"]
  },
  {
    id: "dashboard",
    name: "Dashboard Report",
    description: "Visual metrics for IC meeting",
    fields: ["trendCharts", "anomaliesSummary", "thesisFit"]
  },
  {
    id: "esgImpact",
    name: "ESG Impact Report",
    description: "Impact KPIs & sustainability metrics",
    fields: ["impactMetrics", "ESGScore", "caseStudies"]
  },
  {
    id: "dueDiligence",
    name: "Due Diligence Report",
    description: "Pre-investment risk & thesis fit",
    fields: ["riskAssessment", "anomalyFindings", "thesisAlignment"]
  }
];

