"""Model span adapter shared by graph and reference orchestration."""


class TracedModel:
    def __init__(self, llm, trace):
        self.llm, self.trace = llm, trace

    def generate(self, messages, **kwargs):
        from finrag.agent.policy import current_control

        if control := current_control():
            control.before_model()
        with self.trace.stage("llm_call", {"messages": messages, **kwargs}) as s:
            result = self.llm.generate(messages, **kwargs)
            s["outputs"] = result
            return result
