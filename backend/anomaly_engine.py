"""
Anomaly Detection Engine for FundIQ MVP
Implements 5 rule types for detecting financial anomalies
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import re

from unsupervised_engine import UnsupervisedAnomalyDetector

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detects anomalies in financial documents"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # Configurable thresholds
        self.revenue_spike_threshold = self.config.get('revenue_spike_threshold', 3.0)  # 3x increase
        self.revenue_drop_threshold = self.config.get('revenue_drop_threshold', 0.5)  # 50% decrease
        self.round_number_threshold = self.config.get('round_number_threshold', 1000)  # Flag round numbers above this
        self.duplicate_similarity_threshold = self.config.get('duplicate_similarity_threshold', 0.95)
        
        # Initialize unsupervised detector
        self.unsupervised_detector = UnsupervisedAnomalyDetector(self.config)
    
    def detect_all(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run all anomaly detection rules"""
        all_anomalies = []
        
        # Get numeric field names (common variations)
        numeric_fields = self._get_numeric_fields(rows)
        revenue_fields = self._get_revenue_fields(rows)
        expense_fields = self._get_expense_fields(rows)
        
        # Rule 1: Revenue Anomalies
        revenue_anomalies = self.detect_revenue_anomalies(rows, revenue_fields, numeric_fields)
        all_anomalies.extend(revenue_anomalies)
        
        # Rule 2: Expense Integrity
        expense_anomalies = self.detect_expense_integrity(rows, expense_fields)
        all_anomalies.extend(expense_anomalies)
        
        # Rule 3: Cash Flow Consistency
        cashflow_anomalies = self.detect_cashflow_consistency(rows, numeric_fields)
        all_anomalies.extend(cashflow_anomalies)
        
        # Rule 4: Payroll Patterns
        payroll_anomalies = self.detect_payroll_patterns(rows)
        all_anomalies.extend(payroll_anomalies)
        
        # Rule 5: Declared vs Extracted Mismatch
        mismatch_anomalies = self.detect_declared_mismatch(rows, numeric_fields)
        all_anomalies.extend(mismatch_anomalies)
        
        # Rule 6: Unsupervised ML Detection
        ml_anomalies = self.unsupervised_detector.detect_anomalies(rows)
        all_anomalies.extend(ml_anomalies)
        
        return all_anomalies
    
    def _get_numeric_fields(self, rows: List[Dict[str, Any]]) -> List[str]:
        """Get field names that contain numeric values"""
        if not rows:
            return []
        
        numeric_fields = []
        for row in rows[:10]:  # Sample first 10 rows
            for key, value in row.items():
                if self._is_numeric(value) and key.lower() not in ['page', 'table', 'row_index']:
                    if key not in numeric_fields:
                        numeric_fields.append(key)
        
        return numeric_fields
    
    def _get_revenue_fields(self, rows: List[Dict[str, Any]]) -> List[str]:
        """Get field names related to revenue"""
        revenue_keywords = ['revenue', 'income', 'sales', 'receipt', 'earning', 'turnover']
        all_fields = set()
        
        for row in rows[:10]:
            for key in row.keys():
                key_lower = key.lower()
                if any(keyword in key_lower for keyword in revenue_keywords):
                    all_fields.add(key)
        
        return list(all_fields)
    
    def _get_expense_fields(self, rows: List[Dict[str, Any]]) -> List[str]:
        """Get field names related to expenses"""
        expense_keywords = ['expense', 'cost', 'payment', 'outgoing', 'spend', 'debit']
        all_fields = set()
        
        for row in rows[:10]:
            for key in row.keys():
                key_lower = key.lower()
                if any(keyword in key_lower for keyword in expense_keywords):
                    all_fields.add(key)
        
        return list(all_fields)
    
    def _is_numeric(self, value: Any) -> bool:
        """Check if value is numeric"""
        if value is None:
            return False
        try:
            # Remove common currency symbols and formatting
            str_value = str(value).replace('$', '').replace(',', '').replace(' ', '')
            float(str_value)
            return True
        except (ValueError, TypeError):
            return False
    
    def _to_numeric(self, value: Any) -> Optional[float]:
        """Convert value to numeric"""
        if value is None:
            return None
        try:
            str_value = str(value).replace('$', '').replace(',', '').replace(' ', '')
            return float(str_value)
        except (ValueError, TypeError):
            return None
    
    def detect_revenue_anomalies(self, rows: List[Dict[str, Any]], revenue_fields: List[str], numeric_fields: List[str]) -> List[Dict[str, Any]]:
        """Rule 1: Detect revenue anomalies (spikes, drops, negative values)"""
        anomalies = []
        
        if not revenue_fields:
            # Fallback to numeric fields
            revenue_fields = numeric_fields[:3]  # Use first few numeric fields
        
        for row_idx, row in enumerate(rows):
            for field in revenue_fields:
                value = self._to_numeric(row.get(field))
                if value is None:
                    continue
                
                # Check for negative revenue
                if value < 0:
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'revenue_anomaly',
                        'severity': 'high',
                        'description': f'Negative revenue detected: {field} = {value}',
                        'raw_json': row,
                        'evidence': {'field': field, 'value': value, 'type': 'negative_revenue'}
                    })
        
        # Check for spikes/drops (compare with previous row)
        for row_idx in range(1, len(rows)):
            prev_row = rows[row_idx - 1]
            curr_row = rows[row_idx]
            
            for field in revenue_fields:
                prev_value = self._to_numeric(prev_row.get(field))
                curr_value = self._to_numeric(curr_row.get(field))
                
                if prev_value is None or curr_value is None or prev_value == 0:
                    continue
                
                ratio = curr_value / prev_value
                
                # Spike detection
                if ratio >= self.revenue_spike_threshold:
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'revenue_anomaly',
                        'severity': 'medium',
                        'description': f'Revenue spike detected: {field} increased {ratio:.1f}x ({prev_value} → {curr_value})',
                        'raw_json': curr_row,
                        'evidence': {'field': field, 'prev_value': prev_value, 'curr_value': curr_value, 'ratio': ratio}
                    })
                
                # Drop detection
                elif ratio <= self.revenue_drop_threshold:
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'revenue_anomaly',
                        'severity': 'medium',
                        'description': f'Revenue drop detected: {field} decreased {ratio:.1f}x ({prev_value} → {curr_value})',
                        'raw_json': curr_row,
                        'evidence': {'field': field, 'prev_value': prev_value, 'curr_value': curr_value, 'ratio': ratio}
                    })
        
        return anomalies
    
    def detect_expense_integrity(self, rows: List[Dict[str, Any]], expense_fields: List[str]) -> List[Dict[str, Any]]:
        """Rule 2: Detect expense integrity issues (duplicates, missing descriptions, round numbers)"""
        anomalies = []
        
        # Track seen expense patterns for duplicate detection
        seen_expenses = {}
        
        for row_idx, row in enumerate(rows):
            # Check for missing descriptions in expense rows
            description_fields = [k for k in row.keys() if 'desc' in k.lower() or 'note' in k.lower() or 'memo' in k.lower()]
            expense_amount = None
            expense_field = None
            
            for field in expense_fields:
                amount = self._to_numeric(row.get(field))
                if amount and amount > 0:
                    expense_amount = amount
                    expense_field = field
                    break
            
            if expense_amount is None:
                # Try any numeric field
                for field, value in row.items():
                    amount = self._to_numeric(value)
                    if amount and amount > 0:
                        expense_amount = amount
                        expense_field = field
                        break
            
            if expense_amount:
                # Check for missing description
                has_description = any(
                    row.get(desc_field) and str(row.get(desc_field)).strip()
                    for desc_field in description_fields
                )
                
                if not has_description and expense_amount >= 100:
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'expense_integrity',
                        'severity': 'medium',
                        'description': f'Missing description for expense: {expense_field} = {expense_amount}',
                        'raw_json': row,
                        'evidence': {'field': expense_field, 'amount': expense_amount, 'type': 'missing_description'}
                    })
                
                # Check for round numbers (potential flags)
                if expense_amount >= self.round_number_threshold and expense_amount % 1000 == 0:
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'expense_integrity',
                        'severity': 'low',
                        'description': f'Round number expense: {expense_field} = {expense_amount}',
                        'raw_json': row,
                        'evidence': {'field': expense_field, 'amount': expense_amount, 'type': 'round_number'}
                    })
                
                # Check for duplicates (similar amount and description)
                expense_key = (round(expense_amount, 2), str(row.get(description_fields[0]) if description_fields else ''))
                
                if expense_key in seen_expenses:
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'expense_integrity',
                        'severity': 'high',
                        'description': f'Duplicate expense detected: {expense_field} = {expense_amount} (matches row {seen_expenses[expense_key]})',
                        'raw_json': row,
                        'evidence': {
                            'field': expense_field,
                            'amount': expense_amount,
                            'type': 'duplicate',
                            'matches_row': seen_expenses[expense_key]
                        }
                    })
                else:
                    seen_expenses[expense_key] = row_idx
        
        return anomalies
    
    def detect_cashflow_consistency(self, rows: List[Dict[str, Any]], numeric_fields: List[str]) -> List[Dict[str, Any]]:
        """Rule 3: Check cash flow consistency (balance continuity, mismatched transactions)"""
        anomalies = []
        
        balance_fields = [f for f in numeric_fields if 'balance' in f.lower() or 'total' in f.lower()]
        if not balance_fields:
            return anomalies
        
        # Check balance continuity
        prev_balance = None
        for row_idx, row in enumerate(rows):
            for field in balance_fields:
                balance = self._to_numeric(row.get(field))
                if balance is None:
                    continue
                
                if prev_balance is not None:
                    # Check for large jumps in balance
                    diff = abs(balance - prev_balance)
                    if diff > abs(prev_balance) * 0.5 and abs(prev_balance) > 0:
                        # Check if there's a transaction that explains it
                        transaction_fields = [f for f in numeric_fields if f != field]
                        has_transaction = any(self._to_numeric(row.get(f)) is not None for f in transaction_fields)
                        
                        if not has_transaction:
                            anomalies.append({
                                'row_index': row_idx,
                                'anomaly_type': 'cashflow_consistency',
                                'severity': 'medium',
                                'description': f'Balance inconsistency: {field} jumped from {prev_balance} to {balance} without clear transaction',
                                'raw_json': row,
                                'evidence': {'field': field, 'prev_balance': prev_balance, 'balance': balance, 'diff': diff}
                            })
                
                prev_balance = balance
                break  # Only check first balance field
        
        return anomalies
    
    def detect_payroll_patterns(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rule 4: Detect irregular payroll patterns"""
        anomalies = []
        
        payroll_keywords = ['payroll', 'salary', 'wage', 'pay', 'compensation', 'employee']
        payroll_fields = []
        
        # Find payroll-related fields
        for row in rows[:10]:
            for key in row.keys():
                key_lower = key.lower()
                if any(keyword in key_lower for keyword in payroll_keywords):
                    if key not in payroll_fields:
                        payroll_fields.append(key)
        
        if not payroll_fields:
            return anomalies
        
        # Track payroll amounts
        payroll_amounts = []
        for row_idx, row in enumerate(rows):
            for field in payroll_fields:
                amount = self._to_numeric(row.get(field))
                if amount and amount > 0:
                    payroll_amounts.append((row_idx, amount))
        
        if len(payroll_amounts) < 2:
            return anomalies
        
        # Check for irregular patterns
        amounts = [amt for _, amt in payroll_amounts]
        avg_amount = sum(amounts) / len(amounts)
        
        for row_idx, amount in payroll_amounts:
            # Check for unusually high/low amounts
            if amount > avg_amount * 2:
                anomalies.append({
                    'row_index': row_idx,
                    'anomaly_type': 'payroll_pattern',
                    'severity': 'high',
                    'description': f'Irregular payroll amount: {amount} (avg: {avg_amount:.2f})',
                    'raw_json': rows[row_idx],
                    'evidence': {'amount': amount, 'average': avg_amount, 'type': 'high_variance'}
                })
            elif amount < avg_amount * 0.3 and avg_amount > 0:
                anomalies.append({
                    'row_index': row_idx,
                    'anomaly_type': 'payroll_pattern',
                    'severity': 'medium',
                    'description': f'Unusually low payroll amount: {amount} (avg: {avg_amount:.2f})',
                    'raw_json': rows[row_idx],
                    'evidence': {'amount': amount, 'average': avg_amount, 'type': 'low_variance'}
                })
            
            # Check for duplicates
            if payroll_amounts.count((row_idx, amount)) > 1:
                anomalies.append({
                    'row_index': row_idx,
                    'anomaly_type': 'payroll_pattern',
                    'severity': 'high',
                    'description': f'Duplicate payroll payment detected: {amount}',
                    'raw_json': rows[row_idx],
                    'evidence': {'amount': amount, 'type': 'duplicate'}
                })
        
        return anomalies
    
    def detect_declared_mismatch(self, rows: List[Dict[str, Any]], numeric_fields: List[str]) -> List[Dict[str, Any]]:
        """Rule 5: Compare declared totals with sum of extracted rows"""
        anomalies = []
        
        # Find declared total fields (usually in headers or summary rows)
        total_fields = [f for f in numeric_fields if 'total' in f.lower() or 'sum' in f.lower() or 'grand' in f.lower()]
        declared_totals = {}
        
        # Look for declared totals (often in first or last few rows, or rows with "TOTAL" in text)
        summary_rows = rows[:3] + rows[-3:] if len(rows) > 6 else rows
        
        for row_idx, row in enumerate(rows):
            row_text = ' '.join(str(v) for v in row.values()).upper()
            if 'TOTAL' in row_text or 'SUM' in row_text or 'GRAND' in row_text:
                summary_rows.append(row)
        
        for row in summary_rows:
            for field in total_fields:
                total = self._to_numeric(row.get(field))
                if total:
                    declared_totals[field] = total
        
        # Calculate actual sums from all rows
        for field in total_fields:
            if not declared_totals.get(field):
                continue
            
            declared_total = declared_totals[field]
            actual_sum = sum(
                self._to_numeric(row.get(field)) or 0
                for row in rows
                if self._to_numeric(row.get(field)) is not None
            )
            
            # Check for mismatch (allow 1% tolerance)
            if actual_sum > 0:
                diff = abs(declared_total - actual_sum)
                percent_diff = (diff / actual_sum) * 100
                
                if percent_diff > 1:  # More than 1% difference
                    anomalies.append({
                        'row_index': len(rows) - 1,  # Usually in summary row
                        'anomaly_type': 'declared_mismatch',
                        'severity': 'high',
                        'description': f'Declared total mismatch: {field} declared {declared_total}, calculated {actual_sum} (diff: {diff:.2f}, {percent_diff:.1f}%)',
                        'raw_json': rows[-1] if rows else {},
                        'evidence': {
                            'field': field,
                            'declared_total': declared_total,
                            'actual_sum': actual_sum,
                            'difference': diff,
                            'percent_diff': percent_diff
                        }
                    })
        
        return anomalies


