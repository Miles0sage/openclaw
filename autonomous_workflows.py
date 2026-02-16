"""
🤖 Autonomous Workflow System for OpenClaw
Automatically triggers and manages multi-agent workflows
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from orchestrator import Orchestrator, AgentRole, Message, MessageAudience

logger = logging.getLogger("autonomous_workflows")


class WorkflowTrigger(Enum):
    """What can trigger a workflow"""
    NEW_ORDER = "new_order"
    CLIENT_MESSAGE = "client_message"
    SCHEDULE = "schedule"
    MANUAL = "manual"
    AGENT_COMPLETE = "agent_complete"


class WorkflowStatus(Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkflowStep:
    """A single step in a workflow"""
    agent: AgentRole
    task: str
    timeout: str
    input_params: Dict = None
    output_key: str = None
    retry_count: int = 0
    max_retries: int = 2


@dataclass
class WorkflowExecution:
    """Tracks an executing workflow"""
    workflow_name: str
    trigger: WorkflowTrigger
    status: WorkflowStatus
    current_step: int
    total_steps: int
    started_at: datetime
    context: Dict  # Shared data between steps
    results: List[Dict]  # Results from each step


class AutonomousWorkflowEngine:
    """
    🤖 Autonomous Workflow Engine

    Features:
    - Auto-triggers workflows based on events
    - Manages step execution
    - Handles agent hand-offs
    - Retries on failures
    - Tracks workflow state
    """

    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self.workflows: Dict[str, Dict] = {}
        self.active_executions: Dict[str, WorkflowExecution] = {}
        self.workflow_callbacks: Dict[str, Callable] = {}
        self._load_workflows()

    def _load_workflows(self):
        """Load workflows from config"""
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
                self.workflows = config.get("workflows", {})
                logger.info(f"📋 Loaded {len(self.workflows)} workflows")
        except Exception as e:
            logger.error(f"Failed to load workflows: {e}")
            self.workflows = {}

    def register_trigger(
        self,
        trigger: WorkflowTrigger,
        callback: Callable[[Dict], bool]
    ):
        """
        Register a trigger callback.

        The callback receives event data and returns True if workflow should start.
        """
        trigger_key = trigger.value
        self.workflow_callbacks[trigger_key] = callback
        logger.info(f"🎯 Registered trigger: {trigger_key}")

    async def handle_event(
        self,
        event_type: str,
        event_data: Dict
    ) -> Optional[str]:
        """
        Handle an incoming event and possibly trigger a workflow.

        Returns:
            execution_id if workflow was triggered, None otherwise
        """
        logger.info(f"📥 Event: {event_type}")

        # Check if any workflow should trigger
        for workflow_name, workflow_config in self.workflows.items():
            workflow_trigger = workflow_config.get("trigger")

            if workflow_trigger == event_type:
                logger.info(f"🚀 Triggering workflow: {workflow_name}")
                return await self.start_workflow(workflow_name, event_data)

        return None

    async def start_workflow(
        self,
        workflow_name: str,
        initial_context: Dict = None
    ) -> str:
        """
        Start a workflow execution.

        Returns:
            execution_id for tracking
        """
        if workflow_name not in self.workflows:
            raise ValueError(f"Unknown workflow: {workflow_name}")

        workflow = self.workflows[workflow_name]
        execution_id = f"exec_{workflow_name}_{int(datetime.now().timestamp())}"

        # Parse steps
        steps = []
        for step_config in workflow.get("steps", []):
            agent_key = step_config["agent"]
            agent_role = self._agent_key_to_role(agent_key)

            steps.append(WorkflowStep(
                agent=agent_role,
                task=step_config["task"],
                timeout=step_config.get("timeout", "10m"),
                input_params=step_config.get("params", {}),
                output_key=step_config.get("output_key")
            ))

        # Create execution
        execution = WorkflowExecution(
            workflow_name=workflow_name,
            trigger=WorkflowTrigger(workflow.get("trigger", "manual")),
            status=WorkflowStatus.PENDING,
            current_step=0,
            total_steps=len(steps),
            started_at=datetime.now(),
            context=initial_context or {},
            results=[]
        )

        self.active_executions[execution_id] = execution

        # Start execution in background
        asyncio.create_task(self._execute_workflow(execution_id, steps))

        logger.info(f"🎬 Started workflow: {workflow_name} (exec: {execution_id})")
        return execution_id

    def _agent_key_to_role(self, agent_key: str) -> AgentRole:
        """Convert config agent key to AgentRole"""
        mapping = {
            "project_manager": AgentRole.PM,
            "coder_agent": AgentRole.DEVELOPER,
            "hacker_agent": AgentRole.SECURITY
        }
        return mapping.get(agent_key, AgentRole.PM)

    async def _execute_workflow(
        self,
        execution_id: str,
        steps: List[WorkflowStep]
    ):
        """
        Execute workflow steps sequentially.

        This runs in the background and manages the entire workflow.
        """
        execution = self.active_executions[execution_id]
        execution.status = WorkflowStatus.RUNNING

        logger.info(f"▶️  Executing workflow: {execution.workflow_name}")

        try:
            for idx, step in enumerate(steps):
                execution.current_step = idx
                logger.info(f"📍 Step {idx + 1}/{len(steps)}: {step.agent.value} - {step.task}")

                # Execute step
                result = await self._execute_step(execution, step)

                # Store result
                execution.results.append({
                    "step": idx,
                    "agent": step.agent.value,
                    "task": step.task,
                    "result": result,
                    "timestamp": datetime.now().isoformat()
                })

                # Update context if output_key specified
                if step.output_key and result:
                    execution.context[step.output_key] = result

                # Transition orchestrator workflow state
                await self._transition_workflow_state(step.agent)

            # Workflow completed successfully!
            execution.status = WorkflowStatus.COMPLETED
            logger.info(f"✅ Workflow completed: {execution.workflow_name}")

            # Trigger celebration if applicable
            await self._maybe_celebrate(execution)

        except Exception as e:
            logger.error(f"❌ Workflow failed: {e}")
            execution.status = WorkflowStatus.FAILED

    async def _execute_step(
        self,
        execution: WorkflowExecution,
        step: WorkflowStep
    ) -> Dict:
        """
        Execute a single workflow step.

        This would call the actual agent with the task.
        """
        # TODO: Implement actual agent invocation
        # For now, simulate execution
        logger.info(f"🔧 Executing: {step.agent.value} - {step.task}")

        await asyncio.sleep(0.5)  # Simulate work

        return {
            "agent": step.agent.value,
            "task": step.task,
            "status": "completed",
            "output": f"Simulated result for {step.task}"
        }

    async def _transition_workflow_state(self, agent: AgentRole):
        """Update orchestrator workflow state based on agent"""
        current_state = self.orchestrator.workflow_state

        # Transition based on agent
        transitions = {
            AgentRole.PM: {
                "idle": "client_request",
                "security_audit": "delivery"
            },
            AgentRole.DEVELOPER: {
                "client_request": "development"
            },
            AgentRole.SECURITY: {
                "development": "security_audit"
            }
        }

        next_state = transitions.get(agent, {}).get(current_state)

        if next_state:
            self.orchestrator.transition_workflow_state(next_state, agent)

    async def _maybe_celebrate(self, execution: WorkflowExecution):
        """
        Check if we should celebrate and trigger celebration.

        Celebration triggers:
        - All steps completed
        - Zero security issues
        - Under time/budget
        """
        # Check for perfect execution
        all_success = all(
            r.get("result", {}).get("status") == "completed"
            for r in execution.results
        )

        if all_success:
            achievement = f"🚀 {execution.workflow_name} completed with all agents succeeding!"
            celebration_msg = self.orchestrator.celebrate(achievement)
            logger.info(celebration_msg)

    def get_execution_status(self, execution_id: str) -> Optional[Dict]:
        """Get the status of a workflow execution"""
        execution = self.active_executions.get(execution_id)
        if not execution:
            return None

        return {
            "workflow_name": execution.workflow_name,
            "status": execution.status.value,
            "current_step": execution.current_step,
            "total_steps": execution.total_steps,
            "progress_pct": int((execution.current_step / execution.total_steps) * 100),
            "started_at": execution.started_at.isoformat(),
            "results": execution.results
        }

    def list_active_workflows(self) -> List[Dict]:
        """List all currently active workflow executions"""
        return [
            self.get_execution_status(exec_id)
            for exec_id in self.active_executions.keys()
        ]


# Example: Auto-trigger on new Fiverr order
async def demo_workflow():
    """Demo of autonomous workflow system"""
    logging.basicConfig(level=logging.INFO)

    # Initialize
    orch = Orchestrator()
    engine = AutonomousWorkflowEngine(orch)

    # Simulate new order event
    order_data = {
        "client": "John's Restaurant",
        "project_type": "restaurant_website",
        "budget": 500,
        "deadline_hours": 24,
        "requirements": [
            "Modern design",
            "Online ordering",
            "Mobile responsive",
            "Secure payments"
        ]
    }

    # Start workflow
    exec_id = await engine.start_workflow("fiverr_5star", initial_context=order_data)

    print(f"\n🎬 Started execution: {exec_id}\n")

    # Wait a bit for workflow to progress
    await asyncio.sleep(3)

    # Check status
    status = engine.get_execution_status(exec_id)
    print(f"\n📊 Status:\n{json.dumps(status, indent=2)}\n")

    # Wait for completion
    await asyncio.sleep(5)

    final_status = engine.get_execution_status(exec_id)
    print(f"\n✅ Final Status:\n{json.dumps(final_status, indent=2)}\n")


if __name__ == "__main__":
    asyncio.run(demo_workflow())
