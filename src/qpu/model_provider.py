"""model_provider.py

Model Provider (Module 1): Parse diagonal_model.yaml and provide diagonal values.

API (only 3):
    get_n() -> int
    get_diag_value(z: int) -> float
    get_analytic_terms() -> dict  # raises error if explicit
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Union

import numpy as np
import yaml


# Epsilon for floating-point zero check
_COEFF_EPS = 1e-15


class ModelProviderError(Exception):
    """Model Provider related errors."""
    pass


class ModelProvider:
    """Black box that reads diagonal_model.yaml and provides diagonal values.
    
    Module 2 (sim_runner, qiskit_runner) does not need to know internal implementation.
    - sim_runner: uses only get_n() + get_diag_value(z)
    - qiskit_runner: uses get_n() + get_analytic_terms()
    
    Performance: Both analytic and explicit precompute all values at init,
    so get_diag_value() is always O(1) lookup.
    """
    
    def __init__(self, spec_path: Union[str, Path]) -> None:
        """Load and validate diagonal_model.yaml.
        
        Args:
            spec_path: Path to YAML file
            
        Raises:
            ModelProviderError: On validation failure
        """
        self._spec = self._load_and_validate(spec_path)
        self._n: int = self._spec["n"]
        self._source: str = self._spec["diagonal_components"]["source"]
        
        # Cache terms for analytic (used by get_analytic_terms)
        if self._source == "analytic":
            self._analytic_terms: List[Dict[str, Any]] = self._spec["diagonal_components"]["analytic"]["terms"]
        else:
            self._analytic_terms = []
        
        # Precompute all values (unify analytic/explicit to lookup)
        self._values: np.ndarray = self._precompute_values()
    
    def _load_and_validate(self, spec_path: Union[str, Path]) -> Dict[str, Any]:
        """Load and validate YAML."""
        path = Path(spec_path)
        if not path.exists():
            raise ModelProviderError(f"spec file not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        
        if spec is None or not isinstance(spec, dict):
            raise ModelProviderError("spec must be a YAML mapping")
        
        self._validate_spec(spec)
        return spec
    
    def _validate_spec(self, spec: Dict[str, Any]) -> None:
        """Validate spec (fail-closed policy)."""
        
        # n
        if "n" not in spec:
            raise ModelProviderError("missing required field: n")
        n = spec["n"]
        if not isinstance(n, int) or n < 1:
            raise ModelProviderError(f"n must be a positive integer, got {n!r}")
        
        # bit_order
        if "bit_order" not in spec:
            raise ModelProviderError("missing required field: bit_order")
        if spec["bit_order"] != "lsb":
            raise ModelProviderError(f"bit_order must be 'lsb', got {spec['bit_order']!r}")
        
        # diagonal_components
        if "diagonal_components" not in spec:
            raise ModelProviderError("missing required field: diagonal_components")
        dc = spec["diagonal_components"]
        if not isinstance(dc, dict):
            raise ModelProviderError("diagonal_components must be a mapping")
        
        # source
        if "source" not in dc:
            raise ModelProviderError("missing required field: diagonal_components.source")
        source = dc["source"]
        if source not in ("analytic", "explicit"):
            raise ModelProviderError(f"source must be 'analytic' or 'explicit', got {source!r}")
        
        # Validate block corresponding to source
        if source == "analytic":
            self._validate_analytic(dc, n)
        else:
            self._validate_explicit(dc, n)
    
    def _validate_analytic(self, dc: Dict[str, Any], n: int) -> None:
        """Validate analytic block."""
        analytic = dc.get("analytic")
        if analytic is None or analytic == {}:
            raise ModelProviderError("source='analytic' but 'analytic' block is empty")
        
        if not isinstance(analytic, dict):
            raise ModelProviderError("analytic must be a mapping")
        
        if "kind" not in analytic:
            raise ModelProviderError("missing required field: analytic.kind")
        if analytic["kind"] != "pauli_z_sum":
            raise ModelProviderError(f"unsupported analytic.kind: {analytic['kind']!r}")
        
        if "terms" not in analytic:
            raise ModelProviderError("missing required field: analytic.terms")
        terms = analytic["terms"]
        if not isinstance(terms, list):
            raise ModelProviderError("analytic.terms must be a list")
        
        # Empty terms list is an error
        if len(terms) == 0:
            raise ModelProviderError(
                "analytic.terms is empty. At least one term is required."
            )
        
        # Validate each term
        for i, term in enumerate(terms):
            if not isinstance(term, dict):
                raise ModelProviderError(f"term[{i}] must be a mapping")
            if "c" not in term:
                raise ModelProviderError(f"term[{i}] missing 'c' (coefficient)")
            if "z" not in term:
                raise ModelProviderError(f"term[{i}] missing 'z' (support indices)")
            
            c = term["c"]
            if not isinstance(c, (int, float)):
                raise ModelProviderError(f"term[{i}].c must be a number, got {type(c).__name__}")
            
            # Check for nan/inf (YAML can parse these)
            if not np.isfinite(c):
                raise ModelProviderError(f"term[{i}].c is not finite: {c}")
            
            # Zero coefficient is an error (using floating-point epsilon)
            if abs(c) < _COEFF_EPS:
                raise ModelProviderError(
                    f"term[{i}].c is effectively 0. Remove zero-coefficient terms from spec."
                )
            
            z_support = term["z"]
            if not isinstance(z_support, list):
                raise ModelProviderError(f"term[{i}].z must be a list of qubit indices")
            
            # Empty z_support is a constant term -> allowed (cancels in kappa)
            # Locality check: cannot exceed n-local in n-qubit system
            if len(z_support) > n:
                raise ModelProviderError(
                    f"term[{i}].z has {len(z_support)} indices but n={n}. "
                    f"Maximum locality is {n}-local."
                )
            
            # Duplicate index check
            if len(z_support) != len(set(z_support)):
                raise ModelProviderError(
                    f"term[{i}].z contains duplicate indices: {z_support}"
                )
            
            # Individual index range check
            for idx in z_support:
                if not isinstance(idx, int) or idx < 0 or idx >= n:
                    raise ModelProviderError(
                        f"term[{i}].z contains invalid index {idx!r} for n={n} "
                        f"(valid: 0..{n-1})"
                    )
    
    def _validate_explicit(self, dc: Dict[str, Any], n: int) -> None:
        """Validate explicit block."""
        explicit = dc.get("explicit")
        if explicit is None or explicit == {}:
            raise ModelProviderError("source='explicit' but 'explicit' block is empty")
        
        if not isinstance(explicit, dict):
            raise ModelProviderError("explicit must be a mapping")
        
        if "kind" not in explicit:
            raise ModelProviderError("missing required field: explicit.kind")
        if explicit["kind"] != "dense":
            raise ModelProviderError(f"unsupported explicit.kind: {explicit['kind']!r}")
        
        if "values" not in explicit:
            raise ModelProviderError("missing required field: explicit.values")
        values = explicit["values"]
        if not isinstance(values, list):
            raise ModelProviderError("explicit.values must be a list")
        
        expected_len = 2 ** n
        if len(values) != expected_len:
            raise ModelProviderError(
                f"explicit.values length must be 2^n={expected_len}, got {len(values)}"
            )
        
        # Check each value is numeric and finite
        for i, v in enumerate(values):
            if not isinstance(v, (int, float)):
                raise ModelProviderError(f"explicit.values[{i}] must be a number, got {type(v).__name__}")
            if not np.isfinite(v):
                raise ModelProviderError(f"explicit.values[{i}] is not finite: {v}")
    
    def _precompute_values(self) -> np.ndarray:
        """Precompute diagonal values for all z."""
        size = 1 << self._n
        
        if self._source == "explicit":
            return np.array(
                self._spec["diagonal_components"]["explicit"]["values"],
                dtype=np.float64
            )
        else:
            # analytic: compute for all z
            values = np.zeros(size, dtype=np.float64)
            for z in range(size):
                values[z] = self._compute_analytic_value(z)
            return values
    
    def _compute_analytic_value(self, z: int) -> float:
        """Compute pauli_z_sum.
        
        diag_value(z) = sum_k c_k * prod_{i in support_k} (-1)^{z_i}
        
        where z_i = (z >> i) & 1 (LSB convention)
        Empty support (constant term) yields sign=+1.
        """
        total = 0.0
        for term in self._analytic_terms:
            c = float(term["c"])
            z_support = term["z"]
            
            # Compute parity of bits in support
            # Empty support -> parity=0 -> sign=+1 (constant term)
            parity = 0
            for i in z_support:
                parity ^= (z >> i) & 1
            
            # (-1)^parity = 1 if parity==0 else -1
            sign = 1 - 2 * parity  # 0 -> 1, 1 -> -1
            total += c * sign
        
        return total
    
    # =========================================================================
    # Public API (only 3)
    # =========================================================================
    
    def get_n(self) -> int:
        """Return number of qubits."""
        return self._n
    
    def get_diag_value(self, z: int) -> float:
        """Return diagonal component value for index z.
        
        Args:
            z: Basis state index (0 <= z < 2^n), LSB = qubit 0
            
        Returns:
            Diagonal value (float)
            
        Raises:
            ModelProviderError: If z is out of range
        """
        if not isinstance(z, int):
            raise ModelProviderError(f"z must be an integer, got {type(z).__name__}")
        if z < 0 or z >= (1 << self._n):
            raise ModelProviderError(f"z={z} out of range for n={self._n} (valid: 0..{(1 << self._n) - 1})")
        
        return float(self._values[z])
    
    def get_analytic_terms(self) -> Dict[str, Any]:
        """Return full analytic form.
        
        Returns:
            {"kind": "pauli_z_sum", "terms": [...]}
            
        Raises:
            ModelProviderError: If model is explicit
            
        Note:
            Returns a deep copy to prevent accidental mutation of internal state.
        """
        if self._source != "analytic":
            raise ModelProviderError(
                "get_analytic_terms() is only available for analytic models. "
                f"This model has source='{self._source}'."
            )
        return {
            "kind": self._spec["diagonal_components"]["analytic"]["kind"],
            "terms": copy.deepcopy(self._analytic_terms),
        }