# Payments Platform – Software Requirements Specification
Document No: SRS-PAY-001
Version 2.1
Effective date: 15.09.2026

## 1. Introduction
This specification defines the requirements of the Kuzey Payments Platform. The key words MUST, SHOULD and MAY are to be interpreted as described in RFC 2119.

## 2. Definitions
| Term | Meaning |
|---|---|
| PSP | Payment service provider that processes card payments |
| Chargeback | A payment reversal initiated by the card holder's bank |

"Settlement Window" means the daily period in which captured payments are transferred to merchants.

## 3. Functional requirements
### 3.1 Payments
REQ-001: The Payment Service MUST retry a failed PSP call at most 3 times within 60 seconds.
REQ-002: The Payment Service SHALL NOT store full card numbers.
REQ-003: If the PSP is unavailable, the system SHOULD queue the payment and notify the on-call engineer.

### 3.2 Refunds
REQ-004: Refunds above 1,000 EUR MUST be approved by a finance manager. This requirement depends on REQ-001 and Section 3.1.
REQ-005: The Refund Service MAY issue partial refunds, except for gift card payments.

As a merchant, I want to see refund status in the dashboard so that I can answer customer questions.

Given a refund above 1,000 EUR
When the finance manager approves it
Then the refund is sent to the PSP within 1 hour

## 4. Non-functional requirements
NFR-001: The API MUST respond within 300 ms for 95% of requests.
NFR-002: Card data MUST be processed according to PCI DSS and ISO/IEC 27001.
NFR-003: The platform SHOULD be available 99.95% of the time per month.

## 5. Change history
This version supersedes SRS-PAY-001 version 2.0. Section 3.2 is amended to add REQ-005.
