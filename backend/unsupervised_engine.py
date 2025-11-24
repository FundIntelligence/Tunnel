"""
Unsupervised Anomaly Detection Engine
Uses Isolation Forest to detect outliers in financial data
"""
import logging
import numpy as np
from typing import List, Dict, Any, Optional
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

logger = logging.getLogger(__name__)

class UnsupervisedAnomalyDetector:
    """
    Detects anomalies using unsupervised machine learning (Isolation Forest).
    Identifies rows that are statistically significantly different from the rest.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.contamination = self.config.get('ml_contamination', 0.05)  # Expected % of anomalies
        self.min_samples = self.config.get('ml_min_samples', 20)  # Min rows required to run
        self.random_state = 42
        
    def detect_anomalies(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Run unsupervised anomaly detection on the provided rows.
        Returns a list of detected anomalies.
        """
        if not rows or len(rows) < self.min_samples:
            logger.info(f"Skipping ML detection: insufficient data ({len(rows)} < {self.min_samples})")
            return []
            
        try:
            # 1. Extract numeric features
            features, row_indices, feature_names = self._extract_features(rows)
            
            if not features:
                logger.warning("No numeric features found for ML detection")
                return []
                
            # 2. Preprocess data (Impute missing & Scale)
            # Convert to numpy array
            X = np.array(features)
            
            # Handle missing values (replace with mean)
            imputer = SimpleImputer(strategy='mean')
            X_imputed = imputer.fit_transform(X)
            
            # Scale features (StandardScaler is good for Isolation Forest)
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_imputed)
            
            # 3. Train Isolation Forest
            iso_forest = IsolationForest(
                contamination=self.contamination,
                random_state=self.random_state,
                n_jobs=-1  # Use all CPUs
            )
            
            # Predict: -1 for outliers, 1 for inliers
            predictions = iso_forest.fit_predict(X_scaled)
            
            # Get anomaly scores (lower is more anomalous)
            scores = iso_forest.decision_function(X_scaled)
            
            # 4. Process results
            anomalies = []
            
            for i, prediction in enumerate(predictions):
                if prediction == -1:
                    row_idx = row_indices[i]
                    score = scores[i]
                    
                    # Identify which feature contributed most (simple heuristic: furthest from mean)
                    # In scaled data, mean is 0. So largest absolute value is likely the culprit.
                    row_scaled = X_scaled[i]
                    max_dev_idx = np.argmax(np.abs(row_scaled))
                    key_feature = feature_names[max_dev_idx]
                    key_value = X_imputed[i][max_dev_idx]
                    
                    anomalies.append({
                        'row_index': row_idx,
                        'anomaly_type': 'ml_outlier',
                        'severity': 'medium' if score > -0.1 else 'high',
                        'description': f'Statistical outlier detected by ML model. Unusual {key_feature}: {key_value:.2f}',
                        'raw_json': rows[row_idx],
                        'evidence': {
                            'algorithm': 'isolation_forest',
                            'anomaly_score': float(score),
                            'key_feature': key_feature,
                            'feature_value': float(key_value),
                            'z_score_approx': float(row_scaled[max_dev_idx])
                        }
                    })
            
            logger.info(f"ML detection found {len(anomalies)} anomalies in {len(rows)} rows")
            return anomalies
            
        except Exception as e:
            logger.error(f"Error in unsupervised anomaly detection: {e}")
            return []

    def _extract_features(self, rows: List[Dict[str, Any]]):
        """
        Extract numeric values from rows to create a feature matrix.
        Returns: (list of lists, list of original row indices, list of feature names)
        """
        # 1. Identify numeric fields
        numeric_fields = set()
        sample_size = min(len(rows), 50)
        
        for row in rows[:sample_size]:
            for key, value in row.items():
                if self._is_numeric(value) and key.lower() not in ['page', 'table', 'row_index', 'id']:
                    numeric_fields.add(key)
        
        feature_names = list(numeric_fields)
        if not feature_names:
            return [], [], []
            
        # 2. Build matrix
        features = []
        valid_indices = []
        
        for i, row in enumerate(rows):
            row_features = []
            has_data = False
            
            for field in feature_names:
                val = self._to_numeric(row.get(field))
                if val is not None:
                    row_features.append(val)
                    has_data = True
                else:
                    row_features.append(np.nan) # Mark as missing
            
            if has_data:
                features.append(row_features)
                valid_indices.append(i)
                
        return features, valid_indices, feature_names

    def _is_numeric(self, value: Any) -> bool:
        """Check if value is numeric"""
        if value is None:
            return False
        try:
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
