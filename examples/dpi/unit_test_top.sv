module unit_test_top;
   
  initial begin
     $display("In unit_test_top initial block.");
     dpi_pkg::echo_hello();
  end

endmodule : unit_test_top
