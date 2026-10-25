# State File - baseline-fix branch

## JOB 3b — MONITOR SWEEP FIX (DONE)

**Status**: DONE

**Commit hashes**: 
- bridge/qemu_monitor.py: modified cycle_adc_and_gate function
- tests/test_qemu_monitor_unit.py: rewritten sweep test  
- tests/test_firmware_gpio.py: updated sweep tests
- tests/CHANGES.md: JOB 3 entries added
- tests/MUTATION_LOG.md: mutation test results
- docs/KNOWN_ISSUES.md: JOB 3 findings

**Commands run**:
- Fixed cycle_adc_and_gate: added `stop` parameter, made `qmp.stop()` conditional on `stop=True`
- Updated test_sweep_report_one_row_per_value_over_a_single_monitor: filter qom-set commands, monitor stays running
- Updated test_firmware_gpio.py sweep tests: reflect new contract where stop=False is default
- Added CHANGES.md entries for test changes
- Ran mutation checks and logged results in MUTATION_LOG.md

**Open issues**:
- None remaining for JOB 3b