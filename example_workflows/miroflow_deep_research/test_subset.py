#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 MiromindAI
#
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import sys
from pathlib import Path

def run_gaia_subset(num_tasks=3, benchmark="gaia-validation", agent="claude03_claude_dual", use_sandbox_mode=True):
    """Run a subset of GAIA benchmark for testing
    
    Args:
        num_tasks: Number of tasks to run
        benchmark: Benchmark name
        agent: Agent configuration
        use_sandbox_mode: If True, use optimized sandbox mode to avoid duplicate MCP server launches
    """
    
    # Get the absolute path to run-agent directory
    script_dir = Path(__file__).parent
    run_agent_dir = script_dir / "MiroFlow/apps/run-agent"
    
    if not run_agent_dir.exists():
        print(f"Error: {run_agent_dir} not found. Make sure you're in the DeepResearch directory.")
        print(f"Looking for: {run_agent_dir.absolute()}")
        sys.exit(1)
    
    print(f"Changing to directory: {run_agent_dir.absolute()}")
    os.chdir(run_agent_dir)
    
    # Create results directory
    mode_suffix = "_sandbox" if use_sandbox_mode else "_regular"
    results_dir = f"logs/{benchmark}/test_subset_{num_tasks}{mode_suffix}"
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    
    print(f"Testing {num_tasks} tasks from {benchmark}...")
    print(f"Sandbox mode: {'ENABLED' if use_sandbox_mode else 'DISABLED'}")
    print(f"Results will be saved in: {results_dir}")
    
    # Set environment variable to enable sandbox mode
    env = os.environ.copy()
    if use_sandbox_mode:
        env['MIROFLOW_USE_SANDBOX_MODE'] = 'true'
        print("🚀 Using optimized sandbox mode - MCP servers will launch only once!")
    else:
        env['MIROFLOW_USE_SANDBOX_MODE'] = 'false'
        print("⚠️  Using regular mode - MCP servers may launch multiple times")
    
    # Use conda sovara environment with manually installed packages
    conda_python = "/Users/ferdi/miniconda3/envs/sovara/bin/python"
    cmd = [
        conda_python, "main.py", "common-benchmark",
        f"benchmark={benchmark}",
        f"agent={agent}",
        f"benchmark.execution.max_tasks={num_tasks}",
        "benchmark.execution.max_concurrent=5",
        "benchmark.execution.pass_at_k=1",
        f"hydra.run.dir={results_dir}/run_1"
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False, env=env)
        print("=" * 50)
        print(f"Test completed! Check results in: {results_dir}")
        print("=" * 50)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run GAIA subset for testing")
    parser.add_argument("--num-tasks", "-n", type=int, default=3, 
                       help="Number of tasks to run (default: 3)")
    parser.add_argument("--benchmark", "-b", default="gaia-validation",
                       help="Benchmark name (default: gaia-validation)")
    parser.add_argument("--agent", "-a", default="claude03_claude_dual",
                       help="Agent configuration (default: claude03_claude_dual)")
    parser.add_argument("--disable-sandbox", action="store_true",
                       help="Disable optimized sandbox mode (use regular mode with potential duplicate MCP server launches)")
    
    args = parser.parse_args()
    
    # Default to sandbox mode unless explicitly disabled
    use_sandbox = not args.disable_sandbox
    
    success = run_gaia_subset(args.num_tasks, args.benchmark, args.agent, use_sandbox)
    sys.exit(0 if success else 1)