"""Small deterministic finite-state machine for model-free NPC logic."""
from dataclasses import dataclass,field
from typing import Callable

@dataclass
class FiniteStateMachine:
    state: str
    transitions: dict[str,dict[str,str]] = field(default_factory=dict)
    handlers: dict[str,Callable[[],None]] = field(default_factory=dict)
    def dispatch(self,event: str) -> str:
        target=self.transitions.get(self.state,{}).get(event)
        if target is None: return self.state
        if target not in self.transitions and target not in self.handlers: raise ValueError(f"Unknown target state: {target}")
        self.state=target
        handler=self.handlers.get(target)
        if handler: handler()
        return self.state
