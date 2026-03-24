# Agent examples

We implement example workflows here.

> [!IMPORTANT]  
> For some of the examples, you might need to modify your project root (i.e., run `so-config` and set it to the root of the example repo).

All example workflows except for `debug_examples/` are git modules that live in separate github repos. These are private repos inside our organization and you might need to ask for permission to access them. To clone one of these repos, follow the README.md in the corresponding dir.

If you want to add a new workflow, do the following:
1.  Create a decriptive name for the example (e.g, `example_workflows/chess_text2sql`). The actual example repo will be inside that folder (e.g., `chess_text2sql/CHESS`).
2. Your example workflow will live in its OWN private github repo inside our agops-project organization. It will not be automatically cloned with `sovara`. Create that private repo and ask for help if you don't have the permissions to do so. Push the example repo to our private one. 

For unintialized repos:
```
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/agops-project/XXX.git
git push -u origin main
```
For already initialized repos: 
```
git init # Run to be sure it's initialized
git remote set-url origin https://github.com/agops-project/XXX.git
git push
```

3.  Create a `README.md` inside the example folder (e.g., `chess_text2sql/README.md`) and describe how to clone the submodule (e.g., see `chess_text2sql`). If there are things that might help other people to run it (e.g., problems installing, weird quirks, where files are, etc), put it into that README too.
4.  `cd` into `agent_copilot` project root.
5.  Add the new example repo (e.g., `chess_text2sql/CHESS`) as a submodule:
```
git submodule add https://github.com/agops-project/SOMETHING.git example_workflows/EXAMPLE_FOLDER/SOMETHING
```
6. Add a short description of your workflow below.

## Simple workflows

 - `debug_examples`: Simple workflows to debug our code.

 - `ours_doc_bench`: Questions over PDFs.

 - `ours_human_eval`: Evaluate model-generated code. Download data from https://github.com/openai/human-eval.

## Medium workflows

 - `chess_text2sql`: Used to be SOTA on the BIRD Text2SQL benchmark. https://github.com/ShayanTalaei/CHESS
 
 - `bird`: Our agent for BIRD Text2SQL benchmark.

## Complex workflows

 - `miroflow_deep_research`: MiroFlow open-source deep research agent.

 - `ours_swe_bench`: SWE-bench benchmark with our own agent created by Claude code.
