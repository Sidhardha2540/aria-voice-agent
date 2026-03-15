"""
Transport factory — creates the right transport based on config.
The pipeline doesn't know if audio is coming from a browser or a phone.
"""
from loguru import logger

from agent.config import settings


async def create_transport(runner_args=None):
    """
    Create a transport instance based on settings.transport_mode.

    For WebRTC: uses SmallWebRTC (peer-to-peer, no API key needed)
    For Twilio: uses Pipecat's Twilio transport (requires Twilio credentials)
    For Daily: uses Daily.co transport (requires Daily API key)

    Returns: (transport, transport_type_string)
    """
    mode = settings.transport_mode

    if mode == "webrtc":
        return _create_webrtc_transport(runner_args), "webrtc"
    if mode == "twilio":
        return await _create_twilio_transport(), "twilio"
    if mode == "daily":
        return _create_daily_transport(runner_args), "daily"
    raise ValueError(f"Unknown transport mode: {mode}")


def _create_webrtc_transport(runner_args):
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    logger.info("Creating SmallWebRTC transport")
    return SmallWebRTCTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        webrtc_connection=runner_args.webrtc_connection if runner_args else None,
    )


async def _create_twilio_transport():
    """
    Twilio transport for phone calls.
    Requires: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in .env
    """
    raise NotImplementedError(
        "Twilio transport not yet configured. "
        "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN in .env"
    )


def _create_daily_transport(runner_args):
    """
    Daily.co transport for scalable WebRTC.
    Requires: DAILY_API_KEY in .env
    """
    raise NotImplementedError(
        "Daily transport not yet configured. Set DAILY_API_KEY in .env"
    )
