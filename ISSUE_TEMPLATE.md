# Docker Build Workflow Intermittent Failure Issue

## Problem Summary

The automated dependency update workflow (`update-dependencies.yml`) successfully detects dependency updates and creates commits, but the Docker build jobs (`build_docker`) are being skipped even when all conditions should be met.

## Current Symptoms

- ✅ `check_and_update` job completes successfully
- ✅ `run_ci` job completes successfully  
- ❌ `build_docker` job gets skipped (marked with `-` in GitHub Actions UI)

## Specific Example

**Workflow Run:** https://github.com/MrTyton/AutomatedFanfic/actions/runs/18207918356
**Date:** October 2, 2025 (23:05 UTC)
**Event:** `schedule` (daily 11pm UTC run)

### What Should Have Happened
1. FanFicFare update detected: 4.49.1 → 4.49.2
2. Version bump successful: 1.11.1 → 1.11.2  
3. Commit created: `56b861022501369d5ac43e6ba5f1c6d49b17f2d8`
4. Docker build should have triggered

### What Actually Happened
- Dependencies updated successfully ✅
- Commit created successfully ✅ 
- CI tests passed ✅
- Docker build jobs skipped ❌

### Job Outputs (from logs)
```yaml
changes_detected: true
commit_sha: 56b861022501369d5ac43e6ba5f1c6d49b17f2d8
latest_updated: true
```

## Technical Analysis

### Original Workflow Condition
```yaml
build_docker:
  needs: [check_and_update, run_ci]
  if: needs.check_and_update.outputs.changes_detected == 'true' && needs.check_and_update.outputs.commit_sha != ''
```

### Original Job Output Logic
```yaml
commit_sha: ${{ steps.verify_commit.outputs.verified_sha || steps.commit_changes.outputs.commit_long_sha }}
```

### Suspected Issues
1. **Complex Output Expression**: The fallback logic `verified_sha || commit_long_sha` may have evaluation timing issues
2. **String vs Boolean Comparison**: Potential type coercion issues with `== 'true'` vs `== true`
3. **Job Dependency Race Condition**: Possible GitHub Actions bug with job output propagation

## Attempted Solutions

### Solution 1: Simplified Conditional Logic (Current)
**Commit:** `27f8dcb` (October 2, 2025)

**Changes Made:**
1. Simplified `build_docker` condition:
   ```yaml
   # Before
   if: needs.check_and_update.outputs.changes_detected == 'true' && needs.check_and_update.outputs.commit_sha != ''
   
   # After  
   if: needs.check_and_update.outputs.changes_detected == 'true'
   ```

2. Simplified job output:
   ```yaml
   # Before
   commit_sha: ${{ steps.verify_commit.outputs.verified_sha || steps.commit_changes.outputs.commit_long_sha }}
   
   # After
   commit_sha: ${{ steps.commit_changes.outputs.commit_long_sha }}
   ```

**Rationale:** If `changes_detected` is true, then `commit_sha` will always exist, making the additional check redundant and potentially problematic.

### Previous Investigation Results
- ✅ Verified commit exists in git history: `56b8610`
- ✅ Confirmed job outputs were set correctly in logs
- ✅ Validated all dependent jobs completed successfully
- ✅ Manual workflow trigger shows expected behavior (no changes = no build)

## Testing Plan

### Next Scheduled Run
- **Expected:** October 3, 2025 at 23:00 UTC
- **Monitor:** Check if `build_docker` jobs execute when dependency updates are found
- **Success Criteria:** If updates detected, both `build_matrix` and `merge_and_release` jobs should run

### Manual Testing
```bash
# Trigger manual run when changes available
gh workflow run "Update Dependencies and Run CI"
```

## Fallback Solutions (If Current Fix Fails)

### Option 1: Add Debug Information
Add debug outputs to track job state:
```yaml
- name: Debug job outputs  
  run: |
    echo "changes_detected: ${{ needs.check_and_update.outputs.changes_detected }}"
    echo "commit_sha: ${{ needs.check_and_update.outputs.commit_sha }}"
    echo "commit_sha_length: ${#commit_sha}"
```

### Option 2: Alternative Conditional Logic
Use boolean evaluation instead of string comparison:
```yaml
if: needs.check_and_update.outputs.changes_detected && needs.check_and_update.outputs.commit_sha
```

### Option 3: Restructure Job Dependencies
Make `build_docker` depend only on `check_and_update` and run CI in parallel:
```yaml
build_docker:
  needs: check_and_update
  if: needs.check_and_update.outputs.changes_detected == 'true'
```

### Option 4: Force Job Output Types
Explicitly cast outputs to ensure type consistency:
```yaml
changes_detected: ${{ steps.check_updates.outputs.any_changed == 'true' }}
```

## Related Files
- `.github/workflows/update-dependencies.yml`
- `.github/workflows/docker-image.yml` 
- `.github/actions/bump-version/action.yml`

## Monitoring
- [ ] Next scheduled run (Oct 3, 2025)
- [ ] Manual trigger test when dependencies available
- [ ] Watch for GitHub Actions platform issues

---

**Status:** 🔄 Testing simplified conditional logic (as of Oct 2, 2025)
**Priority:** Medium (affects automated Docker builds but manual builds still work)
**Impact:** Dependency updates may not automatically trigger new Docker images