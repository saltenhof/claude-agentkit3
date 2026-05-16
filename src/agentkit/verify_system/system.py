"""Top-Surface of the verify-system Bounded Context.

``VerifySystem`` is the Capability-A-Top-Komponente of the BC
``verify-system`` (FK-07 §7.4.2, FK-27, ``concept/_meta/bc-cut-decisions.md``
§"BC 2: verify-system"). Cross-BC callers (e.g. ``agentkit.implementation``)
MUST go through this facade and MUST NOT import sub-components such as
``policy_engine.PolicyEngine`` or ``adversarial_orchestrator.challenger.
AdversarialChallenger`` directly (Sichtbarkeitsregel, AC001).

Concept anchor for the long-term contract is FK-27 / formal.verify.commands:

    VerifySystem.run_qa_subflow(story_id, qa_context, target) -> PolicyVerdict

That signature relies on types (``QaContext``, ``ArtifactReference``,
``PolicyVerdict``) that are not yet materialised in code. Therefore the
present facade exposes only the minimal pragmatic operations actually
consumed today by ``agentkit.implementation.phase`` /
``agentkit.implementation.qa_subflow``: returning the adversarial layer
that the QA-subflow assembles, and running the deterministic policy
decision over collected ``LayerResult`` instances. Both operations are
pure delegation -- no business logic in the facade. The full
``run_qa_subflow`` is introduced in a later wave once its dependent
contract types exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.policy_engine.engine import PolicyEngine, VerifyDecision

if TYPE_CHECKING:
    from agentkit.verify_system.protocols import LayerResult, QALayer


@dataclass(frozen=True)
class VerifySystem:
    """Top-Surface of the verify-system Capability-BC.

    Holds the sub-components that the BC composes internally. Cross-BC
    consumers obtain instances through :meth:`create_default` and call
    the published methods of this class. The sub-component fields are
    intentionally typed against the internal classes; consumers must
    not reach into them.

    Attributes:
        policy_engine: Layer-4 deterministic aggregator
            (``agentkit.verify_system.policy_engine``).
        adversarial_challenger: Layer-3 adversarial sparring component
            (``agentkit.verify_system.adversarial_orchestrator``).
    """

    policy_engine: PolicyEngine
    adversarial_challenger: AdversarialChallenger

    @classmethod
    def create_default(
        cls,
        *,
        max_high_findings: int = 0,
    ) -> VerifySystem:
        """Construct a ``VerifySystem`` with default sub-components.

        Args:
            max_high_findings: Threshold for the policy engine. Mirrors
                :class:`PolicyEngine` -- HIGH findings beyond this count
                turn into blocking findings.

        Returns:
            A frozen ``VerifySystem`` with default-configured
            sub-components.
        """
        return cls(
            policy_engine=PolicyEngine(max_high_findings=max_high_findings),
            adversarial_challenger=AdversarialChallenger(),
        )

    def policy_decision(
        self,
        layer_results: list[LayerResult],
    ) -> VerifyDecision:
        """Aggregate ``LayerResult`` instances into a final decision.

        Pure delegation to
        :meth:`agentkit.verify_system.policy_engine.engine.PolicyEngine.decide`.

        Args:
            layer_results: Results from all QA layers executed for this
                subflow round.

        Returns:
            Aggregated :class:`VerifyDecision` from the policy engine.
        """
        return self.policy_engine.decide(layer_results)

    def adversarial_layer(self) -> QALayer:
        """Return the adversarial QA layer (FK-27 Layer 3).

        The layer satisfies the :class:`QALayer` protocol and is
        intended to be appended to the QA-subflow layer list assembled
        by the caller.

        Returns:
            The :class:`AdversarialChallenger` instance held by this
            facade, typed against the public :class:`QALayer` protocol.
        """
        return self.adversarial_challenger
