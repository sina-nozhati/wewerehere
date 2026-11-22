"""Tests for song suggestions rehearsal list and memory contest winner song pick."""

import os
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Event, MemoryItem, MemoryLike, SongSuggestion, SongVote, Ticket
from app.services.song_service import (
    add_song_suggestion,
    check_winner_eligibility,
    get_event_memory_winner,
    get_event_winner_song,
    get_previous_event,
    list_song_suggestions,
    set_winner_song_pick,
    vote_song_suggestion,
)
from app.services.tickets import issue_ticket


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    (tmp_path / "memories").mkdir(parents=True, exist_ok=True)

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSession() as db:
        # Create Event 1 (previous night)
        ev1 = Event(
            slug="event-one",
            title="رویداد شب اول",
            episode_number=1,
            event_at=datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc),
            city="تهران",
            venue="سالن ۱",
            capacity=50,
            ticket_price=0,
            status="sales_open",
            sales_status="open",
        )
        # Create Event 2 (current night)
        ev2 = Event(
            slug="event-two",
            title="رویداد شب دوم",
            episode_number=2,
            event_at=datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc),
            city="تهران",
            venue="سالن ۲",
            capacity=50,
            ticket_price=0,
            status="sales_open",
            sales_status="open",
        )
        db.add(ev1)
        db.add(ev2)
        db.commit()
        ev1_id = ev1.id
        ev2_id = ev2.id

        # Issue tickets for Event 1
        t1, _ = issue_ticket(
            db,
            event_id=ev1_id,
            order_id=None,
            holder_name="سارا احمدی",
            phone="09121111111",
            public_code="1001",
            group_name="A",
        )
        t2, _ = issue_ticket(
            db,
            event_id=ev1_id,
            order_id=None,
            holder_name="علی رضایی",
            phone="09122222222",
            public_code="2002",
            group_name="B",
        )

        # Issue ticket for Event 2
        t3, _ = issue_ticket(
            db,
            event_id=ev2_id,
            order_id=None,
            holder_name="مریم کاظمی",
            phone="09123333333",
            public_code="3003",
            group_name="A",
        )
        db.commit()
        t1_id = t1.id
        t2_id = t2.id
        t3_id = t3.id

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as tc:
        tc._TestingSession = TestingSession
        tc._ev1_id = ev1_id
        tc._ev2_id = ev2_id
        tc._ev1_slug = "event-one"
        tc._ev2_slug = "event-two"
        tc._t1_id = t1_id
        tc._t2_id = t2_id
        tc._t3_id = t3_id
        yield tc

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
    try:
        os.remove(path)
    except OSError:
        pass


def test_get_previous_event_resolution(client):
    with client._TestingSession() as db:
        ev1_id = client._ev1_id
        ev2_id = client._ev2_id

        # Sequential predecessor
        prev = get_previous_event(db, ev2_id)
        assert prev is not None
        assert prev.id == ev1_id

        # First event has no predecessor
        assert get_previous_event(db, ev1_id) is None

        # Gap in IDs (e.g. event 5 after event 2)
        ev5 = Event(
            slug="event-five",
            title="رویداد پنجم",
            episode_number=5,
            event_at=datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc),
            city="تهران",
            venue="سالن ۵",
            capacity=50,
            ticket_price=0,
            status="sales_open",
            sales_status="open",
        )
        db.add(ev5)
        db.commit()
        ev5_id = ev5.id

        # Should resolve highest ID < 5 -> ev2
        resolved = get_previous_event(db, ev5_id)
        assert resolved is not None
        assert resolved.id == ev2_id


def test_memory_winner_calculation_and_tie_breaking(client):
    ev1_id = client._ev1_id
    t1_id = client._t1_id
    t2_id = client._t2_id

    with client._TestingSession() as db:
        # Memory for ticket 1 with 2 likes
        m1 = MemoryItem(
            event_id=ev1_id,
            ticket_id=t1_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="photo1.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="خاطره سارا",
            created_at=datetime(2026, 9, 1, 19, 0, tzinfo=timezone.utc),
        )
        db.add(m1)
        db.commit()
        m1_id = m1.id

        # Add 2 likes to m1
        db.add(MemoryLike(item_id=m1_id, ticket_id=t1_id))
        db.add(MemoryLike(item_id=m1_id, ticket_id=t2_id))

        # Memory for ticket 2 with 5 likes (Clear winner)
        m2 = MemoryItem(
            event_id=ev1_id,
            ticket_id=t2_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="photo2.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="خاطره علی",
            created_at=datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc),
        )
        db.add(m2)
        db.commit()
        m2_id = m2.id

        for i in range(5):
            dummy, _ = issue_ticket(
                db,
                event_id=ev1_id,
                order_id=None,
                holder_name=f"Voter {i}",
                phone=f"0912999000{i}",
                public_code=f"900{i}",
                group_name="A",
            )
            db.add(MemoryLike(item_id=m2_id, ticket_id=dummy.id))
        db.commit()

        winner = get_event_memory_winner(db, ev1_id)
        assert winner is not None
        assert winner["ticket"]["id"] == t2_id
        assert winner["ticket"]["public_code"] == "2002"
        assert winner["ticket"]["holder_name"] == "علی رضایی"
        assert winner["likes_count"] == 5

        # Tie-breaking test: Add m3 for t1 with exact same likes (5), but created later than m2
        m3 = MemoryItem(
            event_id=ev1_id,
            ticket_id=t1_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="photo3.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="خاطره مساوی ولی دیرتر",
            created_at=datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
        )
        db.add(m3)
        db.commit()
        for i in range(5):
            dummy2, _ = issue_ticket(
                db,
                event_id=ev1_id,
                order_id=None,
                holder_name=f"VoterB {i}",
                phone=f"0912888000{i}",
                public_code=f"800{i}",
                group_name="B",
            )
            db.add(MemoryLike(item_id=m3.id, ticket_id=dummy2.id))
        db.commit()

        # m2 was created at 20:00, m3 was created at 21:00 -> m2 must still win tie!
        winner_tied = get_event_memory_winner(db, ev1_id)
        assert winner_tied["ticket"]["id"] == t2_id
        assert winner_tied["memory"]["id"] == m2_id


def test_previous_event_with_zero_memories(client):
    """Verify that when previous event has zero approved memories, eligibility fails cleanly."""
    ev1_id = client._ev1_id
    ev2_id = client._ev2_id
    ev2_slug = client._ev2_slug

    with client._TestingSession() as db:
        # ev1 has no memories
        assert get_event_memory_winner(db, ev1_id) is None

        # Check eligibility
        res = check_winner_eligibility(db, ev2_id, ticket_public_code="1001")
        assert res["isWinnerEligible"] is False
        assert res["isWinner"] is False
        assert res["reason"] == "no_winner_in_previous_event"

    # API call to POST /winner-pick must return 403
    resp = client.post(
        f"/api/events/{ev2_slug}/songs/winner-pick",
        json={"title": "ترانه", "artist": "خواننده", "code": "1001"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "not_winner"



def test_check_winner_eligibility(client):
    ev1_id = client._ev1_id
    ev2_id = client._ev2_id
    t2_id = client._t2_id

    with client._TestingSession() as db:
        # Give t2 an approved memory
        m2 = MemoryItem(
            event_id=ev1_id,
            ticket_id=t2_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="photo2.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="خاطره برنده",
        )
        db.add(m2)
        db.commit()

        # Non-winner code
        res_non_winner = check_winner_eligibility(db, ev2_id, ticket_public_code="1001")
        assert res_non_winner["isWinnerEligible"] is False
        assert res_non_winner["isWinner"] is False

        # Winner code
        res_winner = check_winner_eligibility(db, ev2_id, ticket_public_code="2002")
        assert res_winner["isWinnerEligible"] is True
        assert res_winner["isWinner"] is True
        assert res_winner["winnerName"] == "علی رضایی"
        assert res_winner["winnerCode"] == "2002"


def test_winner_song_endpoints(client):
    ev1_id = client._ev1_id
    ev2_id = client._ev2_id
    ev2_slug = client._ev2_slug
    t2_id = client._t2_id

    with client._TestingSession() as db:
        # Give t2 an approved memory so t2 is winner of ev1
        m2 = MemoryItem(
            event_id=ev1_id,
            ticket_id=t2_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="photo2.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="خاطره برنده",
        )
        db.add(m2)
        db.commit()

    # 1. Non-winner gets 403 on POST /winner-pick
    res = client.post(
        f"/api/events/{ev2_slug}/songs/winner-pick",
        json={"title": "موزیک ۱", "artist": "خواننده ۱", "code": "1001"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == "not_winner"

    # 2. Winner status check
    status_res = client.get(f"/api/events/{ev2_slug}/songs/status?code=2002")
    assert status_res.status_code == 200
    assert status_res.json()["isWinnerEligible"] is True
    assert status_res.json()["winnerName"] == "علی رضایی"

    # 3. Winner submits chosen song
    post_res = client.post(
        f"/api/events/{ev2_slug}/songs/winner-pick",
        json={
            "title": "در امتداد شب",
            "artist": "گوگوش",
            "note": "تقدیم به همه همراهان این شب خاطره‌انگیز",
            "code": "2002",
        },
    )
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["ok"] is True
    assert data["winnerSong"]["title"] == "در امتداد شب"
    assert data["winnerSong"]["artist"] == "گوگوش"
    assert data["winnerSong"]["isWinnerPick"] is True

    # 4. Public GET /winner-pick requires no auth
    pub_res = client.get(f"/api/events/{ev2_slug}/songs/winner-pick")
    assert pub_res.status_code == 200
    assert pub_res.json()["winnerSong"]["title"] == "در امتداد شب"
    assert pub_res.json()["winnerSong"]["suggestedByName"] == "علی رضایی"

    # 5. Memories gallery response embeds winnerSong
    gal_res = client.get(f"/api/events/{ev2_slug}/memories/gallery")
    assert gal_res.status_code == 200
    assert "winnerSong" in gal_res.json()
    assert gal_res.json()["winnerSong"]["title"] == "در امتداد شب"

    # 6. Winner updates their pick
    update_res = client.post(
        f"/api/events/{ev2_slug}/songs/winner-pick",
        json={
            "title": "همسفر",
            "artist": "گوگوش",
            "note": "ویرایش نهایی",
            "code": "2002",
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["winnerSong"]["title"] == "همسفر"

    # Ensure no duplicates in DB
    with client._TestingSession() as db_verify:
        picks = db_verify.query(SongSuggestion).filter_by(event_id=ev2_id, is_winner_pick=True).all()
        assert len(picks) == 1
        assert picks[0].title == "همسفر"


def test_song_suggestions_and_voting_flow(client):
    ev2_slug = client._ev2_slug

    # 1. Validation on empty title/artist
    err_res = client.post(
        f"/api/events/{ev2_slug}/songs/suggest",
        json={"title": "", "artist": ""},
    )
    assert err_res.status_code == 400

    # 2. Add suggestions
    s1 = client.post(
        f"/api/events/{ev2_slug}/songs/suggest",
        json={
            "title": "شازده خانوم",
            "artist": "ستار",
            "note": "خیلی عالیه برای اجرا",
            "suggestedByName": "کامران",
        },
    ).json()
    assert s1["ok"] is True
    s1_id = s1["suggestion"]["id"]

    s2 = client.post(
        f"/api/events/{ev2_slug}/songs/suggest",
        json={
            "title": "مرداب",
            "artist": "حسن شماعی‌زاده",
            "suggestedByName": "نیلوفر",
        },
    ).json()
    assert s2["ok"] is True
    s2_id = s2["suggestion"]["id"]

    # 3. List suggestions (initially 0 votes)
    list_res = client.get(f"/api/events/{ev2_slug}/songs/suggestions?voterId=guest-user-1")
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert len(items) == 2
    assert items[0]["voteCount"] == 0
    assert items[0]["votedByMe"] is False

    # 4. Vote for s2
    vote_res = client.post(
        f"/api/events/{ev2_slug}/songs/suggestions/{s2_id}/vote",
        json={"voterId": "guest-user-1"},
    )
    assert vote_res.status_code == 200
    assert vote_res.json()["voted"] is True
    assert vote_res.json()["voteCount"] == 1

    # Now s2 should be at the top of the list because it has 1 vote
    list_res2 = client.get(f"/api/events/{ev2_slug}/songs/suggestions?voterId=guest-user-1")
    items2 = list_res2.json()["items"]
    assert items2[0]["id"] == s2_id
    assert items2[0]["voteCount"] == 1
    assert items2[0]["votedByMe"] is True

    # 5. Toggle vote on s2 (un-vote)
    unvote_res = client.post(
        f"/api/events/{ev2_slug}/songs/suggestions/{s2_id}/vote",
        json={"voterId": "guest-user-1"},
    )
    assert unvote_res.status_code == 200
    assert unvote_res.json()["voted"] is False
    assert unvote_res.json()["voteCount"] == 0


def test_current_event_memory_winner_eligibility(client):
    """When the contest takes place in the current event itself, its winner is fully recognized."""
    ev2_id = client._ev2_id
    ev2_slug = client._ev2_slug
    t3_id = client._t3_id

    with client._TestingSession() as db:
        # Give t3 an approved memory in event 2 with 3 likes
        m = MemoryItem(
            event_id=ev2_id,
            ticket_id=t3_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="photo_current.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="عکس برنده رویداد جاری",
        )
        db.add(m)
        db.commit()
        m_id = m.id

        dummy, _ = issue_ticket(
            db, event_id=ev2_id, order_id=None, holder_name="Voter 1", phone="09120000001", public_code="7771", group_name="A"
        )
        db.add(MemoryLike(item_id=m_id, ticket_id=dummy.id))
        db.commit()

        # Check eligibility for t3 with code 3003
        res = check_winner_eligibility(db, current_event_id=ev2_id, ticket_public_code="3003", ticket_id=t3_id)
        assert res["isWinnerEligible"] is True
        assert res["isWinner"] is True
        assert res["winnerScope"] == "current_event"
        assert res["winnerName"] == "مریم کاظمی"
        assert res["winnerCode"] == "3003"
        assert res["likesCount"] == 1

    # Call API status
    status_resp = client.get(f"/api/events/{ev2_slug}/songs/status?code=3003")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["isWinnerEligible"] is True
    assert data["winnerScope"] == "current_event"
    assert data["winnerName"] == "مریم کاظمی"

    # Gallery item has isContestWinner flag
    gal_resp = client.get(f"/api/events/{ev2_slug}/memories/gallery")
    assert gal_resp.status_code == 200
    gal_data = gal_resp.json()
    winner_items = [it for it in gal_data["items"] if it.get("isContestWinner")]
    assert len(winner_items) == 1
    assert winner_items[0]["id"] == m_id


def test_previous_winner_gate_access(client):
    """Winner of previous event can enter current event gate with their winning ticket code."""
    ev1_id = client._ev1_id
    ev2_slug = client._ev2_slug
    t2_id = client._t2_id

    with client._TestingSession() as db:
        # t2 (code 2002) is winner of event 1
        m = MemoryItem(
            event_id=ev1_id,
            ticket_id=t2_id,
            status="approved",
            source="guest",
            media_kind="image",
            stored_name="prev_win.jpg",
            mime="image/jpeg",
            size_bytes=1000,
            title="برنده رویداد یک",
        )
        db.add(m)
        db.commit()
        db.add(MemoryLike(item_id=m.id, ticket_id=t2_id))
        db.commit()

    # Gate on event 2 with code 2002 (from event 1)
    gate_resp = client.post(f"/api/events/{ev2_slug}/memories/gate", json={"serial": "2002"})
    assert gate_resp.status_code == 200
    gate_data = gate_resp.json()
    assert "sessionToken" in gate_data
    token = gate_data["sessionToken"]

    # Status check with sessionToken
    st_resp = client.get(
        f"/api/events/{ev2_slug}/songs/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert st_resp.status_code == 200
    st_data = st_resp.json()
    assert st_data["isWinnerEligible"] is True
    assert st_data["winnerScope"] == "previous_event"
    assert st_data["winnerName"] == "علی رضایی"
