# Qlever-w3c-Benchmark
W3C tests for Qlever


 ** under construction ***

Repositories needed:

https://github.com/ad-freiburg/qlever/

https://github.com/w3c/rdf-tests/tree/main/sparql11


_________________________________________________________________________________


w3c_sparql1.1_benchmarking.py argument list:

[0] <w3c_manifests_folders_path (rdf-tests)> 

[1] <Qlever_binary_path>



To build the index, it currently uses the config on e2e/e2e-build-settings.json, which is:

{
  "num-triples-per-batch" : 40000,
  "parser-batch-size" : 1000,
  "ascii-prefixes-only":false
}

_________________________________________________________________________________

For each test, it builds the index, runs the server and sends the query. After it, it terminates the server and starts over again (new test).

While running, it creates the log file (log_output.txt) in the main project folder.
The temporary index files (afterwards deleted) and test-results are currently being placed in "Qlever_binary_path/build/benchmark"

