"""
Test Data Generator for FundIQ MVP
Generates sample files with known anomalies for testing
"""
import pandas as pd
import os
from pathlib import Path

# Create test_data directory
TEST_DATA_DIR = Path(__file__).parent / "test_data"
TEST_DATA_DIR.mkdir(exist_ok=True)


def generate_revenue_anomalies_csv():
    """Generate CSV with revenue anomalies (negative values, spikes)"""
    data = {
        'Date': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'],
        'Revenue': [50000, 52000, -5000, 150000, 51000],  # Negative and spike
        'Description': ['Normal sale', 'Regular transaction', 'Refund', 'Major contract', 'Regular sale']
    }
    df = pd.DataFrame(data)
    file_path = TEST_DATA_DIR / "revenue_anomalies.csv"
    df.to_csv(file_path, index=False)
    print(f"✅ Generated: {file_path}")
    print(f"   Expected anomalies: 2 (1 negative revenue, 1 spike)")
    return file_path


def generate_expense_integrity_xlsx():
    """Generate Excel with expense integrity issues (duplicates, missing descriptions, round numbers)"""
    data = {
        'Date': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-06'],
        'Amount': [1500, 1500, 5000, 2000, 3000, 10000],  # Duplicate and round numbers
        'Description': ['Office supplies', 'Office supplies', '', 'Software license', 'Marketing', 'Consulting'],  # Missing description
        'Category': ['Expense', 'Expense', 'Expense', 'Expense', 'Expense', 'Expense']
    }
    df = pd.DataFrame(data)
    file_path = TEST_DATA_DIR / "expense_integrity.xlsx"
    df.to_excel(file_path, index=False, engine='openpyxl')
    print(f"✅ Generated: {file_path}")
    print(f"   Expected anomalies: 4 (1 duplicate, 1 missing description, 2 round numbers)")
    return file_path


def generate_cashflow_consistency_csv():
    """Generate CSV with cash flow inconsistencies (unbalanced transactions)"""
    data = {
        'Date': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'],
        'Balance': [100000, 120000, 115000, 200000],  # Large jump without transaction
        'Transaction': [20000, -5000, 0, 85000],  # Missing transaction for large balance jump
        'Description': ['Deposit', 'Withdrawal', 'None', 'Transfer']
    }
    df = pd.DataFrame(data)
    file_path = TEST_DATA_DIR / "cashflow_consistency.csv"
    df.to_csv(file_path, index=False)
    print(f"✅ Generated: {file_path}")
    print(f"   Expected anomalies: 1 (balance inconsistency)")
    return file_path


def generate_payroll_anomalies_xlsx():
    """Generate Excel with payroll pattern irregularities"""
    data = {
        'Employee': ['John Doe', 'Jane Smith', 'Bob Johnson', 'Alice Brown', 'Charlie White'],
        'Salary': [5000, 5500, 15000, 5200, 5100],  # Irregular high amount
        'Date': ['2024-01-15', '2024-01-15', '2024-01-15', '2024-01-15', '2024-01-15'],
        'Payment_Type': ['Monthly', 'Monthly', 'Monthly', 'Monthly', 'Monthly']
    }
    df = pd.DataFrame(data)
    file_path = TEST_DATA_DIR / "payroll_anomalies.xlsx"
    df.to_excel(file_path, index=False, engine='openpyxl')
    print(f"✅ Generated: {file_path}")
    print(f"   Expected anomalies: 1 (irregular payroll amount)")
    return file_path


def generate_declared_mismatch_csv():
    """Generate CSV with declared vs extracted mismatch"""
    data = {
        'Item': ['Product A', 'Product B', 'Product C', 'TOTAL'],
        'Amount': [1000, 2000, 1500, 5000],  # Declared total doesn't match sum (4500)
        'Quantity': [10, 20, 15, 45]
    }
    df = pd.DataFrame(data)
    file_path = TEST_DATA_DIR / "declared_mismatch.csv"
    df.to_csv(file_path, index=False)
    print(f"✅ Generated: {file_path}")
    print(f"   Expected anomalies: 1 (declared total mismatch: 5000 vs calculated 4500)")
    return file_path


def main():
    """Generate all test files"""
    print("🧪 Generating test data files with known anomalies...\n")
    
    files = []
    files.append(generate_revenue_anomalies_csv())
    files.append(generate_expense_integrity_xlsx())
    files.append(generate_cashflow_consistency_csv())
    files.append(generate_payroll_anomalies_xlsx())
    files.append(generate_declared_mismatch_csv())
    
    print(f"\n✅ Generated {len(files)} test files in {TEST_DATA_DIR}")
    print("\n📋 Expected anomaly summary:")
    print("   - revenue_anomalies.csv: 2 anomalies (1 negative, 1 spike)")
    print("   - expense_integrity.xlsx: 4 anomalies (1 duplicate, 1 missing desc, 2 round numbers)")
    print("   - cashflow_consistency.csv: 1 anomaly (balance inconsistency)")
    print("   - payroll_anomalies.xlsx: 1 anomaly (irregular amount)")
    print("   - declared_mismatch.csv: 1 anomaly (declared vs extracted mismatch)")
    print("\n🎯 Total expected: ~9 anomalies across all files")
    print(f"\n💡 Upload these files via the frontend to test anomaly detection!")


if __name__ == "__main__":
    main()


