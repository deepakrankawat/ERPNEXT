#!/usr/bin/env bash

set -uo pipefail

SITE="${1:-development.localhost}"
LOG_FILE="$(mktemp)"
FAILED=0
trap 'rm -f "$LOG_FILE"' EXIT

run_suite() {
	: >"$LOG_FILE"
	echo "==> $*"
	bench --site "$SITE" run-tests "$@" 2>&1 | tee "$LOG_FILE"
	bench_status=${PIPESTATUS[0]}
	if [ "$bench_status" -ne 0 ] || grep -Eq '^(FAILED|ERROR:)' "$LOG_FILE"; then
		FAILED=1
	fi
}

# Frappe's app discovery covers controller/page suites. These top-level
# architecture/commerce suites are listed explicitly because v15 does not
# reliably discover them through --app alone.
run_suite --app lex

for module in \
	lex.test_ai_document_processor \
	lex.test_ai_providers \
	lex.test_chat_architecture_scenarios \
	lex.test_client_portal_architecture \
	lex.test_document_export \
	lex.test_lexpack_commerce \
	lex.test_lexpoint_estimation \
	lex.test_pdf_watermark \
	lex.test_persona_workspaces \
	lex.test_srs_acceptance_scenarios \
	lex.test_work_intake
do
	run_suite --module "$module"
done

if [ "$FAILED" -ne 0 ]; then
	echo "One or more Lexocrates test suites failed." >&2
	exit 1
fi

echo "All Lexocrates app and architecture suites passed."
