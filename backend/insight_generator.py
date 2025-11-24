"""
Insights Generator for FundIQ MVP
Aggregates anomalies into actionable insights with severity scoring
"""
import logging
from typing import List, Dict, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class InsightGenerator:
    """Generates insights from detected anomalies"""
    
    def __init__(self):
        self.severity_weights = {
            'high': 3,
            'medium': 2,
            'low': 1
        }
    
    def generate_insights(self, anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate insights from anomalies"""
        if not anomalies:
            return {
                'overall_severity': 'green',
                'risk_score': 0,
                'total_anomalies': 0,
                'insights': [],
                'summary': 'No anomalies detected. Data appears clean.'
            }
        
        # Group anomalies by type
        by_type = defaultdict(list)
        by_severity = defaultdict(int)
        
        for anomaly in anomalies:
            anomaly_type = anomaly.get('anomaly_type', 'unknown')
            severity = anomaly.get('severity', 'low')
            
            by_type[anomaly_type].append(anomaly)
            by_severity[severity] += 1
        
        # Calculate risk score
        risk_score = sum(
            self.severity_weights.get(severity, 1) * count
            for severity, count in by_severity.items()
        )
        
        # Determine overall severity
        if by_severity.get('high', 0) > 0:
            overall_severity = 'red'
        elif by_severity.get('medium', 0) > 5 or risk_score > 10:
            overall_severity = 'yellow'
        else:
            overall_severity = 'green'
        
        # Generate insights per category
        insights = []
        
        for anomaly_type, type_anomalies in by_type.items():
            insight = self._generate_category_insight(anomaly_type, type_anomalies)
            if insight:
                insights.append(insight)
        
        # Sort insights by severity
        severity_order = {'red': 0, 'yellow': 1, 'green': 2}
        insights.sort(key=lambda x: severity_order.get(x.get('severity', 'green'), 2))
        
        # Generate summary
        summary = self._generate_summary(anomalies, insights, overall_severity)
        
        return {
            'overall_severity': overall_severity,
            'risk_score': risk_score,
            'total_anomalies': len(anomalies),
            'insights': insights,
            'summary': summary,
            'breakdown': {
                'by_type': {k: len(v) for k, v in by_type.items()},
                'by_severity': dict(by_severity)
            }
        }
    
    def _generate_category_insight(self, anomaly_type: str, anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate insight for a specific anomaly category"""
        severity_counts = defaultdict(int)
        affected_rows = set()
        
        for anomaly in anomalies:
            severity_counts[anomaly.get('severity', 'low')] += 1
            affected_rows.add(anomaly.get('row_index'))
        
        # Determine category severity
        if severity_counts.get('high', 0) > 0:
            category_severity = 'red'
        elif severity_counts.get('medium', 0) > 2:
            category_severity = 'yellow'
        else:
            category_severity = 'green'
        
        # Generate category-specific summary
        category_name = self._get_category_name(anomaly_type)
        summary = self._get_category_summary(anomaly_type, anomalies, severity_counts)
        
        return {
            'category': category_name,
            'category_type': anomaly_type,
            'severity': category_severity,
            'count': len(anomalies),
            'affected_rows': len(affected_rows),
            'summary': summary,
            'high_severity_count': severity_counts.get('high', 0),
            'medium_severity_count': severity_counts.get('medium', 0),
            'low_severity_count': severity_counts.get('low', 0)
        }
    
    def _get_category_name(self, anomaly_type: str) -> str:
        """Get human-readable category name"""
        names = {
            'revenue_anomaly': 'Revenue Anomalies',
            'expense_integrity': 'Expense Integrity Issues',
            'cashflow_consistency': 'Cash Flow Consistency',
            'payroll_pattern': 'Payroll Pattern Irregularities',
            'declared_mismatch': 'Declared vs Extracted Mismatch'
        }
        return names.get(anomaly_type, anomaly_type.replace('_', ' ').title())
    
    def _get_category_summary(self, anomaly_type: str, anomalies: List[Dict[str, Any]], severity_counts: Dict[str, int]) -> str:
        """Generate category-specific summary text"""
        high_count = severity_counts.get('high', 0)
        medium_count = severity_counts.get('medium', 0)
        total = len(anomalies)
        
        if anomaly_type == 'revenue_anomaly':
            if high_count > 0:
                return f"🚨 {high_count} critical revenue anomalies detected, including negative values or extreme spikes/drops affecting {total} transactions."
            elif medium_count > 0:
                return f"⚠️ {medium_count} revenue anomalies detected with unusual patterns that require review."
            else:
                return f"✓ Minor revenue anomalies detected in {total} transactions."
        
        elif anomaly_type == 'expense_integrity':
            if high_count > 0:
                return f"🚨 {high_count} critical expense integrity issues found, including duplicate expenses affecting {total} transactions."
            elif medium_count > 0:
                return f"⚠️ {medium_count} expense integrity issues detected, including missing descriptions or round numbers."
            else:
                return f"✓ Minor expense integrity issues in {total} transactions."
        
        elif anomaly_type == 'cashflow_consistency':
            if high_count > 0:
                return f"🚨 {high_count} critical cash flow inconsistencies detected affecting {total} balance entries."
            elif medium_count > 0:
                return f"⚠️ {medium_count} cash flow inconsistencies detected with unexplained balance jumps."
            else:
                return f"✓ Minor cash flow consistency issues in {total} entries."
        
        elif anomaly_type == 'payroll_pattern':
            if high_count > 0:
                return f"🚨 {high_count} critical payroll irregularities detected, including duplicate payments or unusual amounts affecting {total} entries."
            elif medium_count > 0:
                return f"⚠️ {medium_count} payroll pattern irregularities detected with variance from expected amounts."
            else:
                return f"✓ Minor payroll pattern variations in {total} entries."
        
        elif anomaly_type == 'declared_mismatch':
            if high_count > 0:
                return f"🚨 {high_count} critical declared total mismatches found where declared totals don't match calculated sums."
            else:
                return f"⚠️ Declared total mismatches detected: discrepancies between declared and calculated totals."
        
        else:
            return f"Found {total} anomalies of type {anomaly_type} ({high_count} high, {medium_count} medium severity)."
    
    def _generate_summary(self, anomalies: List[Dict[str, Any]], insights: List[Dict[str, Any]], overall_severity: str) -> str:
        """Generate overall summary text"""
        total = len(anomalies)
        high_count = sum(1 for a in anomalies if a.get('severity') == 'high')
        medium_count = sum(1 for a in anomalies if a.get('severity') == 'medium')
        
        if overall_severity == 'red':
            return f"🚨 CRITICAL: {high_count} high-severity anomalies detected across {total} total issues. Immediate review required."
        elif overall_severity == 'yellow':
            return f"⚠️ CAUTION: {total} anomalies detected ({medium_count} medium-severity). Review recommended before proceeding."
        else:
            return f"✓ CLEAN: {total} minor anomalies detected. Data quality is acceptable with minimal issues."


