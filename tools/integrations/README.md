### Schema Generator

From the issues thread: Improve schema_generator.py developer experience #11674

(it works by piping the output of a connector into it e.g: docker run <connector> read --config <path> --catalog <path> | python ./tools/integrations/schema_generator.py, but you need to read the code to make that guess) 