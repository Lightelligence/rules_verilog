module unit_test_top;
  initial begin
`ifdef DV_UNIT_VCS
    if (!$test$plusargs("DV_LEGACY_RUNTIME") || !$test$plusargs("DV_UNIT_RUNTIME"))
      $fatal(1, "DV unit runtime arguments did not reach simv");
`endif
`ifdef PWR_AWARE
    if (!$test$plusargs("RTL_DECLARED_RUNTIME") || !$test$plusargs("UCIE_SPEED=16GT"))
      $fatal(1, "RTL unit runtime arguments did not reach simv");
    if (`TIMESCALE_STEP_FS != 100 || `TIMESCALE_PREC_FS != 100)
      $fatal(1, "RTL unit timebase macros must be 100 fs");
    $timeformat(-15, 0, "fs", 0);
    #1;
    if ($sformatf("%t", $realtime) != "100fs")
      $fatal(1, "RTL unit default timescale must be 100fs/100fs");
`endif
    $display("vcs filelist validation");
    $finish;
  end
endmodule
