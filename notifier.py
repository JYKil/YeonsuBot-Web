"""Slack 웹훅 알림 전송"""

import json
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"


def _post_webhook(webhook_url: str, payload: dict) -> bool:
    """Slack Incoming Webhook에 payload를 전송한다."""
    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.error("Slack 응답 오류: status=%s body=%s", resp.status_code, resp.text)
        return False
    except requests.RequestException as e:
        logger.error("Slack 웹훅 요청 오류: %s", e)
        return False


def send_slack_notification(
    webhook_url: str,
    available_dates: list,
    facility_name: str,
    username: str = "",
    checkin: str = "",
    checkout: str = "",
    unavailable_dates: list | None = None,
) -> bool:
    """Slack Incoming Webhook으로 예약 가능 날짜 알림 전송"""
    if not webhook_url:
        logger.warning("Slack 웹훅 URL이 설정되지 않았습니다.")
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    checkin_short = checkin[5:] if len(checkin) >= 10 else checkin
    checkout_short = checkout[5:] if len(checkout) >= 10 else checkout

    available_str = ", ".join(d[4:6] + "-" + d[6:] for d in available_dates)
    text = (
        f"<!channel> 🏖️ 예약 가능 날짜 발견!\n"
        f"요청자: {username}\n"
        f"연수원: {facility_name}\n"
        f"체크인/아웃: {checkin_short}~{checkout_short}\n"
        f"가능: {available_str}\n"
    )
    if unavailable_dates:
        unavailable_str = ", ".join(d[4:6] + "-" + d[6:] for d in unavailable_dates)
        text += f"불가: {unavailable_str}\n"
    text += (
        f"확인시간: {now}\n"
        f"예약링크: https://yeonsu.eseoul.go.kr/main"
    )

    ok = _post_webhook(webhook_url, {"text": text})
    if ok:
        logger.info("Slack 알림 전송 성공")
    return ok


def send_booking_success(
    webhook_url: str,
    facility_name: str,
    booked_date: str,
    username: str = "",
    checkin: str = "",
    checkout: str = "",
) -> bool:
    """예약 성공 알림 전송"""
    if not webhook_url:
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    checkin_short = checkin[5:] if len(checkin) >= 10 else checkin
    checkout_short = checkout[5:] if len(checkout) >= 10 else checkout
    date_str = booked_date[4:6] + "-" + booked_date[6:] if len(booked_date) == 8 else booked_date

    text = (
        f"<!channel> 🎉 예약 완료!\n"
        f"요청자: {username}\n"
        f"연수원: {facility_name}\n"
        f"체크인/아웃: {checkin_short}~{checkout_short}\n"
        f"예약일: {date_str}\n"
        f"확인시간: {now}"
    )

    ok = _post_webhook(webhook_url, {"text": text})
    if ok:
        logger.info("Slack 예약 성공 알림 전송")
    return ok


def send_booking_failure(
    webhook_url: str,
    facility_name: str,
    booked_date: str,
    reason: str = "",
    username: str = "",
) -> bool:
    """예약 실패 알림 전송"""
    if not webhook_url:
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = booked_date[4:6] + "-" + booked_date[6:] if len(booked_date) == 8 else booked_date

    text = (
        f"⚠️ 예약 실패 (모니터링 계속)\n"
        f"요청자: {username}\n"
        f"연수원: {facility_name}\n"
        f"시도일: {date_str}\n"
        f"사유: {reason}\n"
        f"확인시간: {now}"
    )

    ok = _post_webhook(webhook_url, {"text": text})
    if ok:
        logger.info("Slack 예약 실패 알림 전송")
    return ok


def send_test_notification(webhook_url: str) -> bool:
    """연결 테스트용 메시지 전송"""
    if not webhook_url:
        return False
    return _post_webhook(
        webhook_url,
        {"text": "✅ 연수원 알림 테스트 메시지입니다. 웹훅 연결이 정상입니다."},
    )
