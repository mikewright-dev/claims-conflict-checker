# Answer Key: Synthetic Insurance-Denial Case File

**SYNTHETIC DOCUMENT - FOR DEMONSTRATION ONLY.** All people, organizations, and identifiers are fictional.

Patient: Mary Lou Bevredeau (DOB 06/21/1961) | Insurer: Lakeshore Mutual Health | Member ID: LMH-448219037 | PA #: PA-2026-0219884

Values are verbatim text from the PDFs (whitespace collapsed; table cells space-separated).

## Summary

| ID | Type | Field | Severity | Effect on appeal |
|---|---|---|---|---|
| C1 | conflict | Planned surgery date / date of service | low | neutral |
| C2 | conflict | Spinal level of requested fusion | high | helps |
| C3 | conflict | Physical therapy duration | high | helps |
| C4 | conflict | Conservative care duration required by MP-214 | high | helps |
| C5 | conflict | Interventional pain management (epidural steroid injections) | medium | helps |
| C6 | conflict | Spondylolisthesis grade at L4-L5 | high | hurts |
| C7 | conflict | Lower-extremity motor strength / neurological deficit | medium-high | hurts |
| C8 | conflict | Smoking / nicotine status | high | hurts |
| D1 | decoy | MRI exam date (format difference only) | none | neutral |
| D2 | decoy | Spinal level notation (format difference only) | none | neutral |

## Detail

### C1 (conflict): Planned surgery date / date of service

- **Documents involved:** denial_letter.pdf, surgeon_consult_note.pdf
- **Severity:** low
- **Effect on appeal:** neutral
- **Note:** Administrative mismatch; does not affect medical necessity.

| File | Page | Exact value | Role |
|---|---|---|---|
| denial_letter.pdf | 1 | Planned Date of Service: 03/14/2026 | primary |
| surgeon_consult_note.pdf | 4 | Surgery date: Scheduled for 03/21/2026 | primary |

### C2 (conflict): Spinal level of requested fusion

- **Documents involved:** denial_letter.pdf, mri_report.pdf, surgeon_consult_note.pdf
- **Severity:** high
- **Effect on appeal:** helps
- **Note:** Insurer reviewed the wrong level; L5-S1 is essentially normal on MRI.

| File | Page | Exact value | Role |
|---|---|---|---|
| denial_letter.pdf | 1 | Service Reviewed: L5-S1 lumbar spinal fusion | primary |
| surgeon_consult_note.pdf | 4 | Planned procedure: L4-L5 posterior lumbar interbody fusion (PLIF) | primary |
| mri_report.pdf | 1 | L4-5: Grade I anterolisthesis of L4 on L5 | corroborating |
| mri_report.pdf | 2 | L5-S1: Mild disc desiccation. No stenosis. No listhesis. | corroborating |

### C3 (conflict): Physical therapy duration

- **Documents involved:** denial_letter.pdf, pt_discharge_summary.pdf, surgeon_consult_note.pdf
- **Severity:** high
- **Effect on appeal:** helps

| File | Page | Exact value | Role |
|---|---|---|---|
| denial_letter.pdf | 2 | only 4 weeks of physical therapy documented | primary |
| pt_discharge_summary.pdf | 2 | 24 visits over 14 weeks (10/01/2025 to 01/08/2026) | primary |
| pt_discharge_summary.pdf | 1 | Treatment dates 10/01/2025 to 01/08/2026 | corroborating |
| surgeon_consult_note.pdf | 2 | Completed physical therapy for 14 weeks at Prairie Path Physical Therapy (10/01/2025 to 01/08/2026; 24 visits) | corroborating |

### C4 (conflict): Conservative care duration required by MP-214

- **Documents involved:** denial_letter.pdf, medical_policy_MP-214.pdf
- **Severity:** high
- **Effect on appeal:** helps
- **Note:** Denial applied the superseded pre-2026 criterion.

| File | Page | Exact value | Role |
|---|---|---|---|
| denial_letter.pdf | 2 | Medical policy MP-214 requires documentation of at least 6 months of failed conservative care | primary |
| medical_policy_MP-214.pdf | 1 | (b) At least 3 months of failed conservative care, including physical therapy. | primary |
| medical_policy_MP-214.pdf | 2 | conservative care requirement revised from 6 months to 3 months. | corroborating |

### C5 (conflict): Interventional pain management (epidural steroid injections)

- **Documents involved:** denial_letter.pdf, surgeon_consult_note.pdf
- **Severity:** medium
- **Effect on appeal:** helps

| File | Page | Exact value | Role |
|---|---|---|---|
| denial_letter.pdf | 2 | no interventional pain management attempted | primary |
| surgeon_consult_note.pdf | 2 | Epidural steroid injections on 11/12/2025 and 12/17/2025 provided temporary relief only | primary |
| surgeon_consult_note.pdf | 4 | Failure of conservative care, including physical therapy, epidural steroid injections, and oral medications. | corroborating |

### C6 (conflict): Spondylolisthesis grade at L4-L5

- **Documents involved:** mri_report.pdf, surgeon_consult_note.pdf
- **Severity:** high
- **Effect on appeal:** hurts
- **Note:** Surgeon overstates the radiologist's grade; insurer can cite the MRI report.

| File | Page | Exact value | Role |
|---|---|---|---|
| mri_report.pdf | 1 | Grade I anterolisthesis of L4 on L5 | primary |
| surgeon_consult_note.pdf | 3 | Grade II spondylolisthesis at L4-L5 | primary |
| mri_report.pdf | 2 | Grade I anterolisthesis of L4 on L5 at L4-5 | corroborating |

### C7 (conflict): Lower-extremity motor strength / neurological deficit

- **Documents involved:** pt_discharge_summary.pdf, surgeon_consult_note.pdf
- **Severity:** medium-high
- **Effect on appeal:** hurts
- **Note:** Undercuts the 'progressive neurological deficit' path of MP-214 criterion (a). Exams are dated 01/08/2026 (PT) and 02/10/2026 (surgeon).

| File | Page | Exact value | Role |
|---|---|---|---|
| surgeon_consult_note.pdf | 3 | Progressive left foot dorsiflexion weakness, 4/5 | primary |
| pt_discharge_summary.pdf | 3 | strength 5/5 in both lower extremities | primary |
| surgeon_consult_note.pdf | 3 | Ankle dorsiflexion 5/5 4/5 | corroborating |
| pt_discharge_summary.pdf | 3 | Ankle dorsiflexion 5/5 5/5 | corroborating |

### C8 (conflict): Smoking / nicotine status

- **Documents involved:** medical_policy_MP-214.pdf, pt_discharge_summary.pdf, surgeon_consult_note.pdf
- **Severity:** high
- **Effect on appeal:** hurts
- **Note:** If the PT record is accurate, MP-214 exclusion (c) applies.

| File | Page | Exact value | Role |
|---|---|---|---|
| surgeon_consult_note.pdf | 1 | former smoker, quit 2019 | primary |
| pt_discharge_summary.pdf | 1 | current smoker, 1/2 pack per day | primary |
| surgeon_consult_note.pdf | 4 | Patient denies current nicotine use | corroborating |
| medical_policy_MP-214.pdf | 2 | (c) Exclusion: Active nicotine use, unless documented abstinence for at least 6 weeks before surgery | context |

### D1 (decoy): MRI exam date (format difference only)

- **Documents involved:** mri_report.pdf, surgeon_consult_note.pdf
- **Severity:** none
- **Effect on appeal:** neutral
- **Note:** Same date, different format. Not a conflict.

| File | Page | Exact value | Role |
|---|---|---|---|
| mri_report.pdf | 1 | EXAM DATE: January 20, 2026 | primary |
| surgeon_consult_note.pdf | 3 | MRI of the lumbar spine dated 01/20/2026 | primary |

### D2 (decoy): Spinal level notation (format difference only)

- **Documents involved:** mri_report.pdf, surgeon_consult_note.pdf
- **Severity:** none
- **Effect on appeal:** neutral
- **Note:** Same level, different notation. Not a conflict.

| File | Page | Exact value | Role |
|---|---|---|---|
| mri_report.pdf | 1 | L4-5 | primary |
| surgeon_consult_note.pdf | 3 | L4-L5 | primary |

Roles: *primary* = the two conflicting values; *corroborating* = another place in the files stating one side of the same conflict; *context* = policy text that makes the conflict matter.
