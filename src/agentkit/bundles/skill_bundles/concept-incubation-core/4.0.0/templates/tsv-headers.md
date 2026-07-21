# TSV-Header (kopierfertig; Spaltenvertraege: FK-78 §78.3/§78.7-78.9/§78.13)

corpus-baseline.tsv:
path	bytes	sha256	layer	package_id

source-intake.tsv (append-only Hash-Kette; jede Quelle beim Eintreffen; intake_id `INT-<uuid8>-<n>`;
prev_digest der ersten Zeile = 64x"0"; entry_digest = sha256 ueber die kanonisch serialisierten
Feldwerte inkl. prev_digest; Kettenkopf wird in RUN.json register_digests.source_intake_head gepinnt):
intake_id	source_phase	role	path	sha256	registered_at	prev_digest	entry_digest

source-register.tsv:
source_id	source_phase	role	path	sha256	round	participant_id	author_principal_id	genealogy_parents

source-units.tsv:
unit_id	source_id	unit_locator	unit_digest	claim_refs	empty_reason

source-coverage.tsv:
source_id	sha256	review_status	review_artifact	reviewer_principal_id	finding_refs

normative-coverage.tsv:
path	baseline_sha256	current_sha256	change_kind	review_status	review_artifact	reviewer_principal_id	finding_refs

artifact-register.tsv:
path	sha256	artifact_kind	input_refs	declared_class	effective_class	vcs_disposition	declassification_receipt

findings.tsv:
finding_id	severity	status	claim_refs	atom_refs	path	locator	statement	resolution

claims-inventory.tsv:
claim_id	source_id	unit_refs	source_locator	statement	qualifiers	genealogy_parents

disposition-ledger.tsv:
claim_id	synthesis_disposition	disposition_reason	residual_edge	atom_refs	finding_refs

atom-register.tsv:
atom_id	statement	atom_type	qualifiers	normative_status	expected_authority	target_refs	disposition	deferral	claim_refs	receipt_refs
