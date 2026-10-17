# Release Runbook
Document No: RB-002
Version 1.1

## 1. Overview
This runbook describes how the Platform Team ships a release to production every Tuesday.

## 2. Steps
1) The release manager creates the release branch on Monday.
2) QA must sign off the regression suite before 12:00 on Tuesday.
3) The release manager deploys to production between 14:00 and 16:00.
4) If error rates rise above 2% within 30 minutes, the on-call engineer must roll back the release.

## 3. Responsibilities
| Activity | Responsible | Accountable |
|---|---|---|
| Release branch | Release manager | Engineering manager |
| Regression sign-off | QA lead | Engineering manager |
| Rollback | On-call engineer | Release manager |
