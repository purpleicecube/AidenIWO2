# 03 - BUILD RULES + CHECKLIST (Replit)

## What Replit Can Change Safely
- UI clarity and usability
- API ergonomics and docs
- provider integrations
- channel connector implementations
- persistence improvements
- tests and observability

## What Replit Must Not Break
1. Tier boundary rules (Tier 1 orchestrates, Tier 2 executes).
2. PocketFlow flow structure.
3. GCC memory contract behavior.
4. Work order and BDM schema validation.
5. Security baseline controls.

## Security Baseline to Keep
- Bearer role checks
- idempotency behavior
- rate limiting
- correlation IDs
- webhook signature checks

## If Schema Changes Are Needed
1. Update canonical intent in WS006 first.
2. Sync WS014 runtime schemas.
3. Re-run completed and blocked path tests.

## Definition of Done
A task is complete only if:
1. API still runs.
2. UI still runs.
3. `GET /health` passes.
4. work order submit path passes.
5. blocked/BDM path passes.
6. no tier-boundary regression.

## Quick Validation Commands
```bash
curl -s http://localhost:8080/health
python -m pytest WS014_P_PODE/tests/test_mvp_runtime.py -q
```

