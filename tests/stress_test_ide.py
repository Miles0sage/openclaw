#!/usr/bin/env python3
"""
Comprehensive IDE Stress Test — Tests real coding capabilities across all providers.

Tests:
  1. Bug Fix: Find and fix a real bug in generated code (read → diagnose → edit → verify)
  2. Multi-file Refactor: Rename a function across 2 files + update imports
  3. Feature Addition: Add a new method to an existing class, write tests, run them
  4. Code Analysis: Read 3+ files, produce a dependency graph
  5. Error Recovery: Handle a tool that returns an error gracefully
  6. Complex Edit: Insert code at a specific location in a large file

Each test runs on the specified model and reports: PASS/FAIL, tool calls, cost, time.
"""

import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openclaw_ide import execute_with_ide, _compact_tools
from agent_tools import AGENT_TOOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("stress_test")

TOOLS = _compact_tools(AGENT_TOOLS)

# Setup: create temp files for stress tests
STRESS_DIR = "/root/openclaw/tests/stress_workspace"


def setup_workspace():
    """Create test files for stress testing."""
    os.makedirs(STRESS_DIR, exist_ok=True)

    # File 1: Python module with a deliberate bug (off-by-one in pagination)
    with open(f"{STRESS_DIR}/paginator.py", "w") as f:
        f.write('''"""Pagination utility."""

def paginate(items: list, page: int, per_page: int = 10) -> dict:
    """Return a page of items with metadata."""
    total = len(items)
    total_pages = total // per_page  # BUG: should use math.ceil or add 1 for remainder
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


def format_page_info(page_data: dict) -> str:
    """Format pagination info as string."""
    return f"Page {page_data['page']} of {page_data['total_pages']} ({page_data['total']} items)"
''')

    # File 2: Module that imports from paginator
    with open(f"{STRESS_DIR}/api_handler.py", "w") as f:
        f.write('''"""API handler that uses paginator."""
from paginator import paginate, format_page_info


def get_users_page(users: list, page: int) -> dict:
    """Get a page of users."""
    result = paginate(users, page, per_page=5)
    result["display"] = format_page_info(result)
    return result


def search_users(users: list, query: str, page: int = 1) -> dict:
    """Search and paginate users."""
    filtered = [u for u in users if query.lower() in u.lower()]
    return paginate(filtered, page, per_page=5)
''')

    # File 3: A class that needs a new method added
    with open(f"{STRESS_DIR}/calculator.py", "w") as f:
        f.write('''"""Simple calculator class."""
import math


class Calculator:
    """Basic calculator with history."""

    def __init__(self):
        self.history = []

    def add(self, a: float, b: float) -> float:
        result = a + b
        self.history.append(f"{a} + {b} = {result}")
        return result

    def subtract(self, a: float, b: float) -> float:
        result = a - b
        self.history.append(f"{a} - {b} = {result}")
        return result

    def multiply(self, a: float, b: float) -> float:
        result = a * b
        self.history.append(f"{a} * {b} = {result}")
        return result

    def divide(self, a: float, b: float) -> float:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        result = a / b
        self.history.append(f"{a} / {b} = {result}")
        return result

    def get_history(self) -> list:
        return list(self.history)

    def clear_history(self):
        self.history.clear()
''')

    # File 4: Config file (for dependency analysis)
    with open(f"{STRESS_DIR}/config.py", "w") as f:
        f.write('''"""Configuration module."""

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
API_VERSION = "v2"
DEBUG = False

ENDPOINTS = {
    "users": "/api/v2/users",
    "search": "/api/v2/search",
    "calc": "/api/v2/calc",
}
''')

    logger.info(f"Workspace ready at {STRESS_DIR}")


def teardown_workspace():
    """Clean up test workspace."""
    import shutil
    if os.path.exists(STRESS_DIR):
        shutil.rmtree(STRESS_DIR)
    logger.info("Workspace cleaned up")


async def test_bug_fix(model: str) -> dict:
    """Test 1: Find and fix the off-by-one bug in paginator.py.

    The model must:
    1. Read the file
    2. Identify the total_pages bug (doesn't round up)
    3. Fix it with file_edit
    4. Verify the fix works
    """
    prompt = f"""There's a pagination bug in {STRESS_DIR}/paginator.py.
When you have 11 items with per_page=10, total_pages should be 2, but it returns 1.
Find the bug, fix it using file_edit, then verify by reading the file again.
Import math.ceil if needed."""

    result = await execute_with_ide(
        prompt=prompt, tools=TOOLS, job_id="stress_bug_fix", phase="execute",
        model=model, timeout=120,
    )

    # Verify: the fix should use math.ceil or equivalent
    tool_names = [tc["tool"] for tc in result.get("tool_calls", [])]
    has_read = "file_read" in tool_names
    has_edit = "file_edit" in tool_names

    # Check the file was actually fixed
    with open(f"{STRESS_DIR}/paginator.py") as f:
        content = f.read()
    bug_fixed = "ceil" in content or "+ 1" in content or "divmod" in content or "-(-" in content

    passed = has_read and has_edit and bug_fixed
    return {
        "test": "Bug Fix (paginator off-by-one)",
        "model": result.get("model", model),
        "passed": passed,
        "tool_calls": len(result.get("tool_calls", [])),
        "cost": result.get("cost_usd", 0),
        "time": result.get("elapsed_seconds", 0),
        "details": f"read={has_read}, edit={has_edit}, fixed={bug_fixed}",
    }


async def test_rename_refactor(model: str) -> dict:
    """Test 2: Rename 'paginate' to 'get_page' across paginator.py and api_handler.py.

    The model must:
    1. Read both files
    2. Rename the function in paginator.py
    3. Update the import and usage in api_handler.py
    4. Verify both files are consistent
    """
    prompt = f"""Rename the function 'paginate' to 'get_page' in {STRESS_DIR}/paginator.py.
Also update all references in {STRESS_DIR}/api_handler.py (import and calls).
Use file_read to read both files first, then file_edit to make changes."""

    result = await execute_with_ide(
        prompt=prompt, tools=TOOLS, job_id="stress_rename", phase="execute",
        model=model, timeout=120,
    )

    # Verify both files updated
    with open(f"{STRESS_DIR}/paginator.py") as f:
        pag_content = f.read()
    with open(f"{STRESS_DIR}/api_handler.py") as f:
        api_content = f.read()

    func_renamed = "def get_page(" in pag_content
    import_updated = "get_page" in api_content and "from paginator import get_page" in api_content
    old_removed = "def paginate(" not in pag_content

    passed = func_renamed and import_updated and old_removed
    return {
        "test": "Multi-file Rename Refactor",
        "model": result.get("model", model),
        "passed": passed,
        "tool_calls": len(result.get("tool_calls", [])),
        "cost": result.get("cost_usd", 0),
        "time": result.get("elapsed_seconds", 0),
        "details": f"renamed={func_renamed}, import_updated={import_updated}, old_removed={old_removed}",
    }


async def test_feature_addition(model: str) -> dict:
    """Test 3: Add a power() method to Calculator and write+run tests.

    The model must:
    1. Read calculator.py
    2. Add a power(base, exp) method that records history
    3. Create a test file
    4. Run the tests with shell_execute
    """
    prompt = f"""Add a 'power(self, base: float, exponent: float) -> float' method to the Calculator class in {STRESS_DIR}/calculator.py.
It should:
- Calculate base ** exponent
- Add to history like the other methods (e.g., "2 ** 3 = 8")
- Return the result

After adding it, create a test file {STRESS_DIR}/test_calculator.py that tests all Calculator methods (add, subtract, multiply, divide, power, history).
Then run the tests with: shell_execute command="cd {STRESS_DIR} && python3 -m pytest test_calculator.py -v 2>&1 || python3 test_calculator.py" """

    result = await execute_with_ide(
        prompt=prompt, tools=TOOLS, job_id="stress_feature", phase="execute",
        model=model, timeout=180,
    )

    # Verify
    with open(f"{STRESS_DIR}/calculator.py") as f:
        calc_content = f.read()

    has_power = "def power(" in calc_content
    test_exists = os.path.exists(f"{STRESS_DIR}/test_calculator.py")

    tool_names = [tc["tool"] for tc in result.get("tool_calls", [])]
    ran_tests = "shell_execute" in tool_names

    passed = has_power and test_exists and ran_tests
    return {
        "test": "Feature Addition + Tests",
        "model": result.get("model", model),
        "passed": passed,
        "tool_calls": len(result.get("tool_calls", [])),
        "cost": result.get("cost_usd", 0),
        "time": result.get("elapsed_seconds", 0),
        "details": f"power_added={has_power}, test_created={test_exists}, tests_ran={ran_tests}",
    }


async def test_code_analysis(model: str) -> dict:
    """Test 4: Read multiple files and produce a dependency analysis.

    The model must:
    1. Read all 4 files in the workspace
    2. Identify import relationships
    3. Write a dependency report
    """
    prompt = f"""Analyze the codebase in {STRESS_DIR}/.
Read all .py files (paginator.py, api_handler.py, calculator.py, config.py).
Produce a dependency analysis report and write it to {STRESS_DIR}/deps_report.md using file_write.
Include:
- Which files import from which
- Unused modules (if any)
- A suggested import order"""

    result = await execute_with_ide(
        prompt=prompt, tools=TOOLS, job_id="stress_analysis", phase="execute",
        model=model, timeout=120,
    )

    report_exists = os.path.exists(f"{STRESS_DIR}/deps_report.md")
    tool_names = [tc["tool"] for tc in result.get("tool_calls", [])]
    read_count = tool_names.count("file_read")
    wrote_report = "file_write" in tool_names

    passed = report_exists and read_count >= 3 and wrote_report
    return {
        "test": "Multi-file Code Analysis",
        "model": result.get("model", model),
        "passed": passed,
        "tool_calls": len(result.get("tool_calls", [])),
        "cost": result.get("cost_usd", 0),
        "time": result.get("elapsed_seconds", 0),
        "details": f"report={report_exists}, files_read={read_count}, wrote={wrote_report}",
    }


async def test_error_recovery(model: str) -> dict:
    """Test 5: Handle reading a non-existent file gracefully.

    The model must:
    1. Try to read a file that doesn't exist
    2. Recover from the error
    3. Create the file instead
    """
    prompt = f"""Read the file {STRESS_DIR}/missing_module.py.
If it doesn't exist (you'll get an error), create it with file_write containing a simple 'hello()' function that prints 'Hello from stress test'."""

    result = await execute_with_ide(
        prompt=prompt, tools=TOOLS, job_id="stress_error", phase="execute",
        model=model, timeout=90,
    )

    file_created = os.path.exists(f"{STRESS_DIR}/missing_module.py")
    tool_names = [tc["tool"] for tc in result.get("tool_calls", [])]
    tried_read = "file_read" in tool_names
    created = "file_write" in tool_names

    passed = file_created and (tried_read or created)
    return {
        "test": "Error Recovery (missing file)",
        "model": result.get("model", model),
        "passed": passed,
        "tool_calls": len(result.get("tool_calls", [])),
        "cost": result.get("cost_usd", 0),
        "time": result.get("elapsed_seconds", 0),
        "details": f"tried_read={tried_read}, created={created}, file_exists={file_created}",
    }


async def test_complex_edit(model: str) -> dict:
    """Test 6: Add error handling to ALL Calculator methods (try/except + logging).

    The model must:
    1. Read calculator.py
    2. Add type checking to add/subtract/multiply (raise TypeError if not numeric)
    3. Not break existing functionality
    """
    prompt = f"""Read {STRESS_DIR}/calculator.py and add input validation to the add, subtract, and multiply methods.
Each should raise TypeError('Arguments must be numeric') if a or b is not int/float.
Add the check at the start of each method, before the calculation.
Use file_edit for each change. Do NOT modify divide() (it already has validation)."""

    result = await execute_with_ide(
        prompt=prompt, tools=TOOLS, job_id="stress_complex", phase="execute",
        model=model, timeout=120,
    )

    with open(f"{STRESS_DIR}/calculator.py") as f:
        content = f.read()

    has_type_check = "TypeError" in content or "isinstance" in content
    tool_names = [tc["tool"] for tc in result.get("tool_calls", [])]
    has_read = "file_read" in tool_names
    edit_count = tool_names.count("file_edit")

    passed = has_type_check and has_read and edit_count >= 1
    return {
        "test": "Complex Multi-point Edit",
        "model": result.get("model", model),
        "passed": passed,
        "tool_calls": len(result.get("tool_calls", [])),
        "cost": result.get("cost_usd", 0),
        "time": result.get("elapsed_seconds", 0),
        "details": f"validation_added={has_type_check}, read={has_read}, edits={edit_count}",
    }


async def run_stress_test(model: str) -> list:
    """Run all 6 stress tests sequentially on a single model."""
    results = []
    tests = [
        ("1/6", test_bug_fix),
        ("2/6", test_rename_refactor),
        ("3/6", test_feature_addition),
        ("4/6", test_code_analysis),
        ("5/6", test_error_recovery),
        ("6/6", test_complex_edit),
    ]

    for label, test_fn in tests:
        logger.info(f"\n{'='*60}\nRunning {label}: {test_fn.__doc__.split(chr(10))[0].strip()}\n{'='*60}")
        try:
            result = await test_fn(model)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            logger.info(f"{label} {status}: {result['test']} | {result['tool_calls']} calls | ${result['cost']:.6f} | {result['time']}s")
        except Exception as e:
            logger.error(f"{label} ERROR: {e}")
            results.append({
                "test": test_fn.__doc__.split("\n")[0].strip(),
                "model": model,
                "passed": False,
                "tool_calls": 0,
                "cost": 0,
                "time": 0,
                "details": f"ERROR: {e}",
            })

        # Reset workspace between tests 1 and 2 (bug fix modifies paginator)
        # Don't reset between others to test cumulative changes

    return results


async def main():
    """Run stress tests on specified models."""
    models_to_test = sys.argv[1:] if len(sys.argv) > 1 else ["minimax-m2.5"]

    all_results = {}
    overall_start = time.time()

    for model in models_to_test:
        logger.info(f"\n{'#'*60}\n# STRESS TEST: {model}\n{'#'*60}\n")

        # Fresh workspace for each model
        setup_workspace()

        results = await run_stress_test(model)
        all_results[model] = results

        # Summary for this model
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        total_cost = sum(r["cost"] for r in results)
        total_time = sum(r["time"] for r in results)
        total_calls = sum(r["tool_calls"] for r in results)

        print(f"\n{'='*60}")
        print(f"RESULTS: {model}")
        print(f"{'='*60}")
        for r in results:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  [{status}] {r['test']}: {r['tool_calls']} calls, ${r['cost']:.6f}, {r['time']}s")
            if not r["passed"]:
                print(f"         Details: {r['details']}")
        print(f"\n  Score: {passed}/{total} | Cost: ${total_cost:.6f} | Time: {total_time:.1f}s | Tool calls: {total_calls}")

    # Cleanup
    teardown_workspace()

    # Final summary
    overall_time = time.time() - overall_start
    print(f"\n{'#'*60}")
    print(f"# FINAL SUMMARY")
    print(f"{'#'*60}")
    for model, results in all_results.items():
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        cost = sum(r["cost"] for r in results)
        print(f"  {model}: {passed}/{total} passed, ${cost:.6f}")
    print(f"\nTotal time: {overall_time:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
