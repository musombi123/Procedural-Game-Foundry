from simulation.ai_behaviour.fsm import FiniteStateMachine
from gameplay.quests.graph import validate_quest_graph
def test_fsm_transition():
    machine=FiniteStateMachine("idle",{"idle":{"seen":"alert"},"alert":{"lost":"idle"}})
    assert machine.dispatch("seen")=="alert"
def test_quest_cycle_detected():
    result=validate_quest_graph([{"id":"a","requires":["b"]},{"id":"b","requires":["a"]}])
    assert not result["valid"]
