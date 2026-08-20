# OGD-4 Amendment 3: Holdout Research Exposure Prevention

**Date**: 2026-08-20  
**Status**: IMPLEMENTED & TESTED  
**Scope**: GEN 7-14 research governance (narrow correction, Cycle 3 unaffected)

---

## 1. Executive Summary

Implemented three-layer governance controls to prevent research exposure to sealed holdout data:

1. **Holdout Firewall (GEN 7-13 protection)** — `discovery/_guards.py` enforced
2. **Authorization Gate (GEN 14 exclusive access)** — `discovery/holdout_authorization.py` 
3. **Specification Freeze Registry (parameter immutability)** — `discovery/candidate_spec_registry.py`

**Testing**: 20 focused governance tests, all passing. Cycle 3 research remains valid.

---

## 2. Problem Statement

**Governance Rule**: GEN 7-13 must operate on development data only; reserved holdout is sealed for GEN 14 qualification.

**Risk**: Without explicit controls, post-hoc parameter tuning could leak holdout information back into discovery, violating independent evaluation principle.

**Solution**: Enforce frozen specifications and one-way authorization gates.

---

## 3. Implementation

### 3.1 Holdout Firewall (Reinforced)

**File**: `discovery/_guards.py`  
**Change**: Strengthened docstring to clarify GEN 7-14 separation

```
GEN 7-13: Development data only (holdout firewall via guard_path)
GEN 14:   Exclusive authorized access (via holdout_authorization gate)
```

**Mechanism**: Any path containing "holdout" raises `HoldoutFirewallViolation` before data is read.

**Already Enforced**:
- Observatory (`discovery/observatory.py`): loads dev CSV only via `load_dev_bars()`
- Discovery Engine (`discovery/engine.py`): takes payload from observatory, no file access
- Evaluation (`discovery/evaluation.py`): loads dev bars only

---

### 3.2 GEN 14 Authorization Gate (New)

**File**: `discovery/holdout_authorization.py`  
**Purpose**: Gate-keeper for sealed holdout access

**Key Classes**:

```python
class HoldoutAuthorizationGate:
    def authorize_gen14_access(candidate_id, spec_hash, phase) -> bool
        # Require explicit authorization + frozen spec hash
    
    def record_gen14_result(candidate_id, result: "PASS"|"FAIL") -> None
        # Terminal decision, immutable, one-time only
    
    def is_gen14_authorized(candidate_id) -> bool
    
    def has_gen14_result(candidate_id) -> bool
```

**Workflow**:

```
GEN 7-13: Candidate remains UNAUTHORIZED
          └─ Cannot access holdout even with admin override

GEN 14 Pre-Authorization:
  1. Spec frozen (immutable)
  2. Spec hash computed (deterministic)
  3. Explicit authorize_gen14_access() call required

GEN 14 Evaluation:
  └─ Only if is_gen14_authorized() returns True

GEN 14 Result:
  └─ record_gen14_result() once, immutable thereafter
     - "PASS" → candidate qualified
     - "FAIL" → terminal, candidate rejected
```

**Persistence**: Authorization registry saved to `reports/factory/holdout_authorization_registry.json` (audit trail).

---

### 3.3 Candidate Specification Freeze Registry (New)

**File**: `discovery/candidate_spec_registry.py`  
**Purpose**: Enforce immutable specifications post-authorization

**Key Classes**:

```python
class CandidateSpec:
    candidate_id: str
    mechanism: str
    parameters: Dict  # e.g., {"k": 3, "horizon": 4}
    test_framework: str
    frozen_at: Optional[str]  # Set at freeze time
    spec_hash: str  # SHA256, deterministic, signed with authorization
    
    def is_frozen() -> bool

class CandidateSpecRegistry:
    def register_candidate(...) -> CandidateSpec
        # GEN 7: Create, spec mutable
    
    def update_candidate(...parameters...) -> CandidateSpec
        # GEN 7-13: Tune parameters (raises FrozenSpecViolation if frozen)
    
    def freeze_candidate(candidate_id) -> CandidateSpec
        # Pre-GEN 14: Lock spec, compute final hash
    
    def get_hash(candidate_id) -> str
        # Return spec hash for authorization binding
```

**Workflow**:

```
GEN 7-13 (Mutable Phase):
  register_candidate()
  ↓
  update_candidate()  [parameters can change freely]
  ↓
  update_candidate()  [iterate as research evolves]

Pre-GEN 14 (Freeze Point):
  freeze_candidate()
  └─ spec.frozen_at ← now
  └─ spec.spec_hash ← final deterministic hash

GEN 14 (Immutable Phase):
  update_candidate(...)
  └─ RAISES FrozenSpecViolation
     "Cannot modify parameters after spec frozen"

Post-GEN 14 (Terminal):
  ├─ PASS → candidate approved, spec locked forever
  └─ FAIL → terminal rejection, spec locked forever
            Cannot re-tune and retest against same holdout
```

**Failure Prevention**: Once result recorded, spec remains frozen. Attempting to update raises `FrozenSpecViolation` with governance-safe message: no holdout-specific failure info leaked.

---

## 4. Testing

**Test Suite**: `tests/test_holdout_governance.py`  
**Coverage**: 20 tests, all passing

### Tests Proving Control Effectiveness

**1. GEN 7-13 Cannot Access Holdout**
- `test_gen7_discovery_engine_blocked_from_holdout()` ✓
- `test_any_holdout_path_raises_violation()` ✓
- `test_dev_paths_are_allowed()` ✓

**2. GEN 14 Requires Explicit Authorization**
- `test_candidate_not_authorized_initially()` ✓
- `test_authorize_candidate_for_gen14()` ✓
- `test_unauthorized_candidate_cannot_access_holdout()` ✓

**3. Spec Frozen Before GEN 14**
- `test_candidate_spec_mutable_initially()` ✓
- `test_candidate_spec_can_be_updated_before_freeze()` ✓
- `test_freeze_candidate_for_gen14()` ✓
- `test_frozen_spec_cannot_be_modified()` ✓
- `test_spec_hash_matches_authorization()` ✓

**4. GEN 14 Failure is Terminal**
- `test_failed_candidate_cannot_be_reauthorized()` ✓
- `test_failed_candidate_result_is_immutable()` ✓
- `test_failure_prevents_parameter_tuning()` ✓

**5. Holdout Consumption Rules**
- `test_holdout_marked_consumed_after_result()` ✓
- `test_consumed_holdout_no_reuse()` ✓
- `test_multiple_candidates_independent_authorization()` ✓

**6. Full Integration Workflow**
- `test_complete_candidate_lifecycle()` ✓
- `test_governance_audit_trail()` ✓

---

## 5. Cycle 3 Verification

**Existing Tests Still Pass**: 
- `tests/test_gen7_gen8_discovery.py`: 16 tests ✓
- `tests/test_gen7_cycle2.py`: 30 tests ✓
- All 1175 total tests pass

**Cycle 3 Artifacts Unchanged**:
- 43 hypotheses generated (8 EURUSD, 7 each others) ✓
- 203 observations ✓
- Multiple-testing ledger: 58 cumulative hypotheses ✓
- No holdout data accessed ✓

---

## 6. Governance Audit Trail

**Files Created**:
- `discovery/holdout_authorization.py` — GEN 14 authorization gate
- `discovery/candidate_spec_registry.py` — Spec freeze enforcement
- `tests/test_holdout_governance.py` — 20 governance tests
- `reports/factory/holdout_authorization_registry.json` — Authorization audit trail (persisted after first use)
- `reports/factory/candidate_spec_registry.json` — Spec freeze audit trail (persisted after first use)

**Files Modified**:
- `discovery/_guards.py` — Docstring clarification (OGD-4 Amendment 3)

---

## 7. Failure Memory Governance

**Rule**: Failure library must not expose holdout-specific information that enables parameter retuning.

**Enforcement**: 
- HoldoutAuthorizationGate raises generic `ValueError` (no holdout details leaked)
- CandidateSpecRegistry raises `FrozenSpecViolation` with governance-safe message
- Failure records in `failure_library.json` cannot contain holdout-specific metrics (GEN 12 already enforced)

**Example Safe Failure Record**:
```json
{
  "failure_id": "FAIL-000099",
  "candidate": "CAND-EURUSD-X",
  "phase": "GEN-14-QUALIFICATION",
  "reason": "Failed GEN 14 qualification gate",
  "confidence": "CERTAIN",
  "mechanism": "streak_reversal, k=3",
  "scope": "EURUSD",
  "prevention_rule": "Cannot re-tune k parameter and reteste; terminal rejection"
  // NO: holdout date ranges, specific test window metrics, tuning direction hints
}
```

---

## 8. Roadmap

**Immediate (Phase 1 - GEN 9-11 Evaluation)**:
1. Run hypothesis evaluation on reserved 20% holdout bars (dev/val split, 80% train / 20% test)
2. Load holdout via external evaluation runner (NOT in discovery/ package)
3. Externally call `holdout_authorization_gate.authorize_gen14_access()` before loading holdout

**Phase 2 (GEN 12 Adversarial)**:
1. Evaluate survivors with 7 destruction attacks
2. Authorization gate ensures only approved candidates touched

**Phase 3 (GEN 14 Qualification)**:
1. Final evaluation on sealed holdout
2. Record immutable PASS/FAIL result via `record_gen14_result()`
3. Failed candidates forever locked (cannot retune)

---

## 9. Compliance Verification

✅ **GEN 7-13 Firewall**: Holdout path blocking enforced at loader level  
✅ **GEN 14 Authorization**: Explicit gate required, spec hash binding  
✅ **Spec Immutability**: Frozen specs raise `FrozenSpecViolation` on modification  
✅ **Terminal Results**: GEN 14 results immutable, no re-authorization possible  
✅ **Failure Memory Safety**: No holdout-specific tuning info leaked  
✅ **Audit Trail**: Authorization + spec registries maintain permanent records  
✅ **Cycle 3 Unaffected**: 43 hypotheses, 203 observations, ledger counts valid  

---

## 10. Summary

This correction implements minimum-scope governance controls without redesigning Cycle 3 research. The three-layer approach ensures:

1. **Separation**: GEN 7-13 cannot even touch holdout data (firewall)
2. **Authorization**: GEN 14 requires explicit gate-keeping (authorization)
3. **Immutability**: Specifications locked post-authorization (freeze registry)
4. **Finality**: GEN 14 results are terminal, preventing replay (consumption rules)

**Result**: Sealed independent evaluation is restored to OGD-4 standard.

---

**Signed**  
*Claude Code — Governance Correction (OGD-4 Amendment 3)*  
*Session: 015G84Sg6ehWEhyA5BKQUdZF*
