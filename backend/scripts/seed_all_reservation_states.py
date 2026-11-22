"""Seed all possible reservation and ticket states for testing.

States covered:
1. Pending Orders (در انتظار):
   - Single person | Digital only | Text receipt only
   - Single person | Physical card | Image receipt only
   - Multi (2 persons) | Physical card | Both Text + Image receipt
   - Multi (3 persons) | Digital only | Text receipt only
2. Approved Orders (تأیید شده):
   - Single person | Physical card | Active Ticket in Group A
   - Multi (2 persons) | Digital only | Active Tickets in Group B (Table grouping)
   - Multi (3 persons) | Physical card | Active Tickets in Group A
3. Rejected Orders (رد شده):
   - Single person | Digital only | Reason: unreadable receipt
   - Multi (2 persons) | Physical card | Reason: payment amount mismatch
   - Single person | Digital only | Reason: empty note
4. Tickets (جدول رزروها):
   - Active ticket linked to order
   - Revoked ticket linked to order
   - Active manual ticket (walk-in, no order)
   - Revoked manual ticket
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Event, Order, PaymentReceipt, Ticket
from app.services.tickets import issue_ticket


def seed_receipt_files():
    storage_receipts = Path("storage/receipts")
    storage_receipts.mkdir(parents=True, exist_ok=True)
    sources = list(Path("uploads/receipts").glob("*.*")) + list(storage_receipts.glob("*.*"))
    if sources:
        target1 = storage_receipts / "seed-receipt-1.jpg"
        target2 = storage_receipts / "seed-receipt-2.jpg"
        if not target1.exists():
            shutil.copy(sources[0], target1)
        if not target2.exists():
            shutil.copy(sources[1] if len(sources) > 1 else sources[0], target2)


def seed_for_event(db: Session, ev: Event):
    print(f"Seeding reservations for Event #{ev.id}: {ev.title} ({ev.slug})")

    # Ensure event capacity is sufficient for testing approvals
    if ev.capacity < 60:
        ev.capacity = 60
        db.add(ev)

    # Prefix used for seed phone numbers to keep them unique per event
    prefix = f"090{ev.id}"
    test_phones = [f"{prefix}{i:07d}" for i in range(1, 25)]

    # Clean previous seed data for this event
    old_orders = db.scalars(select(Order).where(Order.event_id == ev.id, Order.phone.in_(test_phones))).all()
    for o in old_orders:
        db.query(PaymentReceipt).where(PaymentReceipt.order_id == o.id).delete()
        db.query(Ticket).where(Ticket.order_id == o.id).delete()
        db.delete(o)

    old_tickets = db.scalars(select(Ticket).where(Ticket.event_id == ev.id, Ticket.phone.in_(test_phones))).all()
    for t in old_tickets:
        db.delete(t)

    db.commit()

    now = datetime.now(timezone.utc)

    # -------------------------------------------------------------
    # 1. PENDING ORDERS (در انتظار تأیید)
    # -------------------------------------------------------------
    # 1.1 تک‌نفره | فقط دیجیتال | فقط رسید متنی
    o1 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000001",
        names_json=json.dumps(["سهراب سپهری"], ensure_ascii=False),
        status="payment_submitted",
        wants_physical_card=False,
        created_at=now - timedelta(hours=1),
    )
    db.add(o1)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o1.id,
        text="واریز کارت به کارت از بانک ملی به شماره کارت اعلام شده - پیگیری: ۴۸۱۲۰۹۳",
        file_path="",
        submitted_at=now - timedelta(hours=1),
    ))

    # 1.2 تک‌نفره | کارت فیزیکی | با تصویر فیش رسید
    o2 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000002",
        names_json=json.dumps(["پروین اعتصامی"], ensure_ascii=False),
        status="payment_submitted",
        wants_physical_card=True,
        created_at=now - timedelta(hours=3),
    )
    db.add(o2)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o2.id,
        text="",
        file_path="receipts/seed-receipt-1.jpg",
        submitted_at=now - timedelta(hours=3),
    ))

    # 1.3 دونفره | کارت فیزیکی | هم رسید متنی و هم تصویر فیش
    o3 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000003",
        names_json=json.dumps(["نیما یوشیج", "عالیه جهانگیر"], ensure_ascii=False),
        status="payment_submitted",
        wants_physical_card=True,
        created_at=now - timedelta(hours=5),
    )
    db.add(o3)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o3.id,
        text="انتقال پایا بابت ۲ بلیت همراه با کارت فیزیکی، کد رهگیری شبا ۹۴۸۲۱۰۳۹",
        file_path="receipts/seed-receipt-2.jpg",
        submitted_at=now - timedelta(hours=5),
    ))

    # 1.4 سه‌نفره (گروهی) | فقط دیجیتال | فقط رسید متنی
    o4 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000004",
        names_json=json.dumps(["مهدی اخوان ثالث", "فروغ فرخزاد", "فریدون فرخزاد"], ensure_ascii=False),
        status="payment_submitted",
        wants_physical_card=False,
        created_at=now - timedelta(hours=8),
    )
    db.add(o4)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o4.id,
        text="پرداخت اینترنتی از درگاه شاپرک - شناسه تراکنش ۷۷۳۰۹۱",
        file_path="",
        submitted_at=now - timedelta(hours=8),
    ))

    # -------------------------------------------------------------
    # 2. APPROVED ORDERS (تأیید شده با بلیت صادر شده)
    # -------------------------------------------------------------
    # 2.1 تک‌نفره | کارت فیزیکی | گروه A
    o5 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000005",
        names_json=json.dumps(["احمد شاملو"], ensure_ascii=False),
        status="approved",
        wants_physical_card=True,
        created_at=now - timedelta(days=1),
        reviewed_at=now - timedelta(days=1, hours=-1),
    )
    db.add(o5)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o5.id,
        text="پرداخت از اپلیکیشن آپ، پیگیری ۵۵۹۰۲۱",
        file_path="receipts/seed-receipt-1.jpg",
        submitted_at=now - timedelta(days=1),
    ))
    issue_ticket(
        db,
        event_id=ev.id,
        order_id=o5.id,
        holder_name="احمد شاملو",
        phone=o5.phone,
        group_name="A",
        wants_physical_card=True,
    )

    # 2.2 دونفره | فقط دیجیتال | گروه B (میز دونفره)
    o6 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000006",
        names_json=json.dumps(["سیمین دانشور", "جلال آل احمد"], ensure_ascii=False),
        status="approved",
        wants_physical_card=False,
        created_at=now - timedelta(days=2),
        reviewed_at=now - timedelta(days=2, hours=-2),
    )
    db.add(o6)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o6.id,
        text="واریز از همراه بانک سامان به شماره حساب",
        file_path="receipts/seed-receipt-2.jpg",
        submitted_at=now - timedelta(days=2),
    ))
    for name in ["سیمین دانشور", "جلال آل احمد"]:
        issue_ticket(
            db,
            event_id=ev.id,
            order_id=o6.id,
            holder_name=name,
            phone=o6.phone,
            group_name="B",
            wants_physical_card=False,
        )

    # 2.3 سه‌نفره | کارت فیزیکی | گروه A (میز سه‌نفره)
    o7 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000007",
        names_json=json.dumps(["محمدرضا شجریان", "همایون شجریان", "مژگان شجریان"], ensure_ascii=False),
        status="approved",
        wants_physical_card=True,
        created_at=now - timedelta(days=3),
        reviewed_at=now - timedelta(days=3, hours=-1),
    )
    db.add(o7)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o7.id,
        text="واریز ساتنا بابت ۳ بلیت ویژه، شماره پیگیری ۶۶۱۸۹۰",
        file_path="",
        submitted_at=now - timedelta(days=3),
    ))
    for name in ["محمدرضا شجریان", "همایون شجریان", "مژگان شجریان"]:
        issue_ticket(
            db,
            event_id=ev.id,
            order_id=o7.id,
            holder_name=name,
            phone=o7.phone,
            group_name="A",
            wants_physical_card=True,
        )

    # -------------------------------------------------------------
    # 3. REJECTED ORDERS (رد شده با یادداشت ادمین)
    # -------------------------------------------------------------
    # 3.1 تک‌نفره | فقط دیجیتال | دلیل: فیش ناخوانا
    o8 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000008",
        names_json=json.dumps(["صادق هدایت"], ensure_ascii=False),
        status="rejected",
        admin_note="تصویر فیش ارسالی ناخوانا است و تاریخ و مبلغ واریز قابل مشاهده نیست. لطفاً تصویر باکیفیت و واضح ارسال فرمایید.",
        wants_physical_card=False,
        created_at=now - timedelta(days=1, hours=2),
        reviewed_at=now - timedelta(days=1),
    )
    db.add(o8)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o8.id,
        text="",
        file_path="receipts/seed-receipt-1.jpg",
        submitted_at=now - timedelta(days=1, hours=2),
    ))

    # 3.2 دونفره | کارت فیزیکی | دلیل: کسری مبلغ
    o9 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000009",
        names_json=json.dumps(["بزرگ علوی", "محمدعلی جمال‌زاده"], ensure_ascii=False),
        status="rejected",
        admin_note="مبلغ واریزی معادل ۱ بلیت است در حالی که درخواست رزرو برای ۲ نفر ثبت شده است. لطفاً مابه‌التفاوت را تسویه نمایید.",
        wants_physical_card=True,
        created_at=now - timedelta(days=2, hours=4),
        reviewed_at=now - timedelta(days=2),
    )
    db.add(o9)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o9.id,
        text="واریز از تجارت کارت",
        file_path="",
        submitted_at=now - timedelta(days=2, hours=4),
    ))

    # 3.3 تک‌نفره | فقط دیجیتال | بدون یادداشت ادمین
    o10 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000010",
        names_json=json.dumps(["هوشنگ ابتهاج"], ensure_ascii=False),
        status="rejected",
        admin_note="",
        wants_physical_card=False,
        created_at=now - timedelta(days=3),
        reviewed_at=now - timedelta(days=3, hours=-2),
    )
    db.add(o10)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o10.id,
        text="شماره تراکنش ۹۹۸۱۲۳",
        file_path="",
        submitted_at=now - timedelta(days=3),
    ))

    # -------------------------------------------------------------
    # 4. SPECIAL TICKET STATES (جدول رزروها / بلیت‌ها)
    # -------------------------------------------------------------
    # 4.1 بلیت لغو شده متصل به سفارش
    o11 = Order(
        event_id=ev.id,
        phone=f"{prefix}0000011",
        names_json=json.dumps(["غلامحسین ساعدی"], ensure_ascii=False),
        status="approved",
        wants_physical_card=False,
        created_at=now - timedelta(days=4),
        reviewed_at=now - timedelta(days=4, hours=-1),
    )
    db.add(o11)
    db.flush()
    db.add(PaymentReceipt(
        order_id=o11.id,
        text="پرداخت حضوری در محل",
        file_path="",
        submitted_at=now - timedelta(days=4),
    ))
    t_revoked, _ = issue_ticket(
        db,
        event_id=ev.id,
        order_id=o11.id,
        holder_name="غلامحسین ساعدی",
        phone=o11.phone,
        group_name="B",
        wants_physical_card=False,
    )
    t_revoked.status = "revoked"
    t_revoked.revoked_at = now - timedelta(hours=2)

    # 4.2 بلیت دستی (مهمان ویژه / بدون سفارش آنلاین) - فعال - کارت فیزیکی - گروه A
    issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="کیهان کلهر (مهمان ویژه)",
        phone=f"{prefix}0000012",
        group_name="A",
        wants_physical_card=True,
    )

    # 4.3 بلیت دستی (بدون سفارش آنلاین) - لغو شده - فقط دیجیتال - گروه B
    t_manual_revoked, _ = issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="شهرام ناظری (لغو شده)",
        phone=f"{prefix}0000013",
        group_name="B",
        wants_physical_card=False,
    )
    t_manual_revoked.status = "revoked"
    t_manual_revoked.revoked_at = now - timedelta(days=1)

    db.commit()


def run_seed():
    seed_receipt_files()
    db: Session = SessionLocal()
    try:
        events = db.scalars(select(Event).order_by(Event.id.asc())).all()
        if not events:
            print("No events found in database.")
            return

        for ev in events:
            seed_for_event(db, ev)

        print("✅ Seed completed successfully for all events!")
    except Exception as e:
        db.rollback()
        print(f"❌ Error during seed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
