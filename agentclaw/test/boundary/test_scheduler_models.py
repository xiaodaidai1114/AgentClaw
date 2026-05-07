import pytest
from pydantic import ValidationError

from agentclaw.scheduler.models import (
    CreateJobRequest,
    TriggerConfig,
    TriggerType,
    UpdateJobRequest,
    WebhookConfig,
)


pytestmark = pytest.mark.boundary


def _cron_trigger() -> TriggerConfig:
    return TriggerConfig(type=TriggerType.CRON, expression="0 * * * *")


def test_create_job_rejects_enabled_webhook_with_blank_secret():
    with pytest.raises(ValidationError) as exc_info:
        CreateJobRequest(
            name="nightly",
            workflow_id="wf-1",
            trigger=_cron_trigger(),
            webhook=WebhookConfig(enabled=True, secret="   "),
        )

    assert "webhook.secret is required" in str(exc_info.value)


def test_update_job_allows_disabling_webhook_without_secret():
    request = UpdateJobRequest(webhook=WebhookConfig(enabled=False, secret=None))

    assert request.webhook.enabled is False
    assert request.webhook.secret is None


def test_interval_trigger_requires_at_least_one_interval_field():
    with pytest.raises(ValidationError) as exc_info:
        TriggerConfig(type=TriggerType.INTERVAL)

    assert "interval trigger requires" in str(exc_info.value)


def test_date_trigger_requires_run_date():
    with pytest.raises(ValidationError) as exc_info:
        TriggerConfig(type=TriggerType.DATE)

    assert "date trigger requires" in str(exc_info.value)
