# V2 Triple Gate v1

Adds one token-free command that creates three useful proof artifacts:

1. V2 proof bundle refresh
2. Latest-run health audit
3. Executive board packet summary

Tool:

    tools/v2_triple_gate.py

Outputs:

    reports/v2_triple_gate.txt
    reports/v2_triple_gate.json
    reports/v2_board_packet_latest.txt

Run:

    PYTHONNOUSERSITE=1 python3 tools/v2_triple_gate.py

Skip refresh and only summarize existing state:

    PYTHONNOUSERSITE=1 python3 tools/v2_triple_gate.py --no-refresh

Purpose:

    Give the operator and executive agents one quick summary of whether V2 is ready for the next proof step.
