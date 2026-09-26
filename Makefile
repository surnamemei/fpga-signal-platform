SIM ?= iverilog
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/rtl/fir_stream.sv
TOPLEVEL = fir_stream
MODULE = tb.test_fir_cocotb
include $(shell cocotb-config --makefiles)/Makefile.sim
