# cocotb build and run of rtl/fir_stream.sv for ONE coefficient configuration.
# Normally driven by the top-level Makefile (`make rtl`). Direct use, from the repo root:
#   make -f tb/cocotb.mk SIM=icarus FIR_CONFIG=stress
#
# SIM is cocotb's simulator *name*. For Icarus Verilog that is "icarus": "iverilog" is only
# the name of its compiler executable, and cocotb has no simulator called "iverilog".

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)
PYTHON ?= python3
SIM ?= icarus
FIR_CONFIG ?= default

ifeq ($(SIM),iverilog)
  $(error SIM=iverilog is the Icarus executable name; cocotb's simulator name is SIM=icarus)
endif
ifneq ($(SIM),icarus)
  $(error SIM=$(SIM): only icarus is wired up here; Verilator runs the SV cross-check (make xsim))
endif

COCOTB_MAKEFILES := $(shell cocotb-config --makefiles 2>/dev/null)
ifeq ($(COCOTB_MAKEFILES),)
  $(error cocotb is not installed in this Python environment; run: pip install -e ".[dev]")
endif

FIR_CONFIG_NAMES := $(shell $(PYTHON) -m fpga_signal.rtl_configs names 2>/dev/null)
ifeq ($(FIR_CONFIG_NAMES),)
  $(error $(PYTHON) cannot import fpga_signal; run: pip install -e ".[dev]")
endif
ifeq ($(filter $(FIR_CONFIG),$(FIR_CONFIG_NAMES)),)
  $(error unknown FIR_CONFIG=$(FIR_CONFIG); known configs: $(FIR_CONFIG_NAMES))
endif
# Coefficients are compile-time parameters, so every config gets its own build directory:
# a shared one would silently reuse a simulator build compiled with other taps. The
# "default" config has no overrides, so it tests the defaults written in the RTL source.
FIR_PARAM_ARGS := $(shell $(PYTHON) -m fpga_signal.rtl_configs iverilog-args $(FIR_CONFIG))

TOPLEVEL_LANG = verilog
RTL_SOURCES ?= $(REPO_ROOT)/rtl/fir_stream.sv
VERILOG_SOURCES = $(RTL_SOURCES)
COCOTB_TOPLEVEL = fir_stream
COCOTB_TEST_MODULES = tb.test_fir_cocotb
SIM_BUILD ?= $(REPO_ROOT)/sim_build/$(SIM)-$(FIR_CONFIG)
COCOTB_RESULTS_FILE ?= $(SIM_BUILD)/results.xml
COMPILE_ARGS += -Wall $(FIR_PARAM_ARGS)
CUSTOM_COMPILE_DEPS += $(REPO_ROOT)/fpga_signal/rtl_configs.py $(REPO_ROOT)/tb/cocotb.mk

# The tests use their own seeded generators; pinning cocotb's global seed keeps logs identical too.
COCOTB_RANDOM_SEED ?= 5305

export FIR_CONFIG
export PYTHONPATH := $(REPO_ROOT)$(if $(PYTHONPATH),:$(PYTHONPATH))

include $(COCOTB_MAKEFILES)/Makefile.sim
