# FPGA Signal Platform: Gate 0 simulation flow. Board-independent: no FPGA vendor tools.
# `make help` lists the targets.

PYTHON ?= python3
# cocotb's simulator name. The Icarus Verilog executable is `iverilog`; cocotb calls it `icarus`.
SIM ?= icarus
ifeq ($(SIM),iverilog)
  $(error SIM=iverilog is the Icarus executable name; cocotb's simulator name is SIM=icarus)
endif
FIR_CONFIGS ?= $(shell $(PYTHON) -m fpga_signal.rtl_configs names 2>/dev/null)
VECTORS := verification/vectors.csv
RESULTS = $(foreach c,$(FIR_CONFIGS),sim_build/$(SIM)-$(c)/results.xml)
YOSYS ?= $(shell command -v yosys 2>/dev/null || command -v yowasp-yosys 2>/dev/null)

.PHONY: all help gate0 ci test vectors rtl lint xsim mutation synth clean check-python check-icarus check-verilator

all: gate0

help:
	@echo "Gate 0 simulation flow (details in README.md):"
	@echo "  make gate0     test + vectors + rtl: the Gate 0 criterion (default target)"
	@echo "  make ci        everything GitHub Actions runs: gate0 + lint + xsim + mutation + synth"
	@echo "  make test      Python golden-model and tooling tests (pytest)"
	@echo "  make vectors   write the deterministic 10,000-sample vectors to $(VECTORS)"
	@echo "  make rtl       cocotb RTL regression, SIM=$(SIM), configs: $(or $(FIR_CONFIGS),<python package not installed>)"
	@echo "  make lint      Verilator -Wall lint of the RTL for every config"
	@echo "  make xsim      SystemVerilog-only testbench on Icarus and Verilator"
	@echo "  make mutation  inject known RTL bugs; every one must be caught"
	@echo "  make synth     board-independent Yosys synthesis of every config (pip install -e \".[synth]\")"
	@echo "  make clean     remove generated vectors and simulation builds"

gate0:
	$(MAKE) --no-print-directory test
	$(MAKE) --no-print-directory vectors
	$(MAKE) --no-print-directory rtl

ci: gate0
	$(MAKE) --no-print-directory lint
	$(MAKE) --no-print-directory xsim
	$(MAKE) --no-print-directory mutation
	$(MAKE) --no-print-directory synth

test:
	$(PYTHON) -m pytest -q

vectors:
	$(PYTHON) verification/generate_vectors.py

$(VECTORS): verification/generate_vectors.py $(wildcard fpga_signal/*.py)
	$(PYTHON) verification/generate_vectors.py

check-python:
	@$(PYTHON) -c "import fpga_signal, cocotb" 2>/dev/null || { echo "error: '$(PYTHON)' cannot import fpga_signal and cocotb; activate the venv and run: pip install -e \".[dev]\"" >&2; exit 1; }

check-icarus:
	@command -v iverilog >/dev/null || { echo "error: iverilog not found. Install Icarus Verilog (Ubuntu: sudo apt install iverilog; macOS: brew install icarus-verilog)" >&2; exit 1; }
	@iverilog -V 2>&1 | sed -n 1p

check-verilator:
	@command -v verilator >/dev/null || { echo "error: verilator not found (Ubuntu: sudo apt install verilator; macOS: brew install verilator)" >&2; exit 1; }
	@verilator --version

# Every config runs even if an earlier one fails; the strict checker then decides.
rtl: check-python check-icarus $(VECTORS)
	@status=0; \
	for cfg in $(FIR_CONFIGS); do \
	  echo "==> RTL regression: SIM=$(SIM) FIR_CONFIG=$$cfg"; \
	  $(MAKE) --no-print-directory -f tb/cocotb.mk SIM=$(SIM) FIR_CONFIG=$$cfg PYTHON=$(PYTHON) sim || status=1; \
	done; \
	$(PYTHON) verification/check_results.py $(RESULTS) || status=1; \
	exit $$status

lint: check-python check-verilator check-icarus
	@for cfg in $(FIR_CONFIGS); do \
	  echo "==> verilator --lint-only -Wall (FIR_CONFIG=$$cfg)"; \
	  verilator --lint-only -Wall --top-module fir_stream \
	    $$($(PYTHON) -m fpga_signal.rtl_configs verilator-args $$cfg) rtl/fir_stream.sv || exit 1; \
	done
	@echo "==> parameter guard: an undersized accumulator (ACC_W=34) must be refused"
	@mkdir -p sim_build
	@iverilog -g2012 -Wall -o sim_build/acc_guard.vvp -Pfir_stream.ACC_W=34 rtl/fir_stream.sv
	@if vvp -n sim_build/acc_guard.vvp > sim_build/acc_guard.log 2>&1; then \
	  echo "error: fir_stream accepted ACC_W=34; its parameter guard did not fire" >&2; exit 1; fi
	@grep -q "guaranteed-safe width" sim_build/acc_guard.log || { cat sim_build/acc_guard.log >&2; exit 1; }

xsim: check-python check-icarus check-verilator $(VECTORS)
	$(PYTHON) verification/xsim.py $(FIR_CONFIGS)

mutation: check-python check-icarus $(VECTORS)
	$(PYTHON) verification/mutation_test.py

# Generic (technology-independent) synthesis: proves the RTL is synthesizable, latch-free and has
# no multiple drivers or combinational loops. No FPGA part, vendor tool or board is involved.
synth: check-python
	@test -n "$(YOSYS)" || { echo "error: yosys not found; run: pip install -e \".[synth]\" (YoWASP build) or install Yosys" >&2; exit 1; }
	@mkdir -p sim_build/synth
	@for cfg in $(FIR_CONFIGS); do \
	  log=sim_build/synth/$$cfg.log; \
	  $(YOSYS) -q -l $$log -p "read_verilog -sv rtl/fir_stream.sv; $$($(PYTHON) -m fpga_signal.rtl_configs yosys-args $$cfg) hierarchy -check -top fir_stream; proc; check -assert; synth -top fir_stream; check -assert; stat" > /dev/null \
	    || { echo "error: synthesis failed for FIR_CONFIG=$$cfg (see $$log)" >&2; exit 1; }; \
	  if grep -qiE "warning|^Latch inferred" $$log; then grep -iE "warning|^Latch inferred" $$log >&2; exit 1; fi; \
	  echo "==> yosys synth FIR_CONFIG=$$cfg: $$(grep -E '^ +[0-9]+ +cells$$' $$log | tail -1 | xargs), $$(grep -E '[0-9]+ +.._S?DFF' $$log | tail -2 | awk '{n += $$1} END {print n}') flip-flops, no latches, no warnings"; \
	done

clean:
	rm -rf sim_build results.xml $(VECTORS)
