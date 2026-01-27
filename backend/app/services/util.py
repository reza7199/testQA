def issue_body(bug: dict) -> str:
    return f"""Bug ID: {bug.get('bug_id')}

**Severity:** {bug.get('severity')}
**Workflow:** {bug.get('workflow')}

## Expected
{bug.get('expected')}

## Actual
{bug.get('actual')}

## Repro steps
{bug.get('repro_steps')}

## Evidence
- Trace: {bug.get('trace_path')}
- Screenshot: {bug.get('screenshot_path')}
- Video: {bug.get('video_path')}

## Console errors
{bug.get('console_errors')}

## Network failures
{bug.get('network_failures')}

## Suspected root cause
{bug.get('suspected_root_cause')}

## Code location guess
{bug.get('code_location_guess')}

**Confidence:** {bug.get('confidence')}
"""
