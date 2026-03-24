# CHESS Text2SQL

Used to be SOTA on the BIRD benchmark.

## Clone git submodule

You need access to [CHESS github repo](https://github.com/agops-project/ShayanTalaei-CHESS). If you don't have it.

```
git submodule update --init example_workflows/chess_text2sql/CHESS
```

## Packages

Here are a couple of personal notes:

The `requirements.txt` doesn't contain all deps and leads to version conflicts. I just dumped all my pip packages into `my_install.txt`. This definitely isn't ideal but `pip install -r my_install.txt` should give you a working version.

## Set up

You first need to preprocess the data (and download it). See CHESS/README.md

## Running

I introdcued a `--num_tasks` parameter if you don't want to run the whole BRID benchmark for debugging, so you might want to modify this. The run scripts are in `run` (e.g., `sh run/run_main_ir_ss_ch.sh`, `sh run/develop_main_ir_ss_ch.sh` --- `develop` = `so-record` version). See the CHESS/README.md to see what version of the agent different scripts are using.