#!/usr/bin/env python3
"""Standalone PM-Bench v9 week generator.

This builder intentionally does not reuse the fixed v8 step scaffold or prose
templates. It generates a single 7-day week with:
- unique day archetypes
- irregular per-day time signatures
- richer cue / state / lure pools
- more reschedules and cross-day reminders
- lighter week-level narrative continuity
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from copy import deepcopy

from pm_bench import compute_scenario_groundtruth, validate_scenario


DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

STATE_CHANNEL_CONFIG = {
    "clock": {"mode": "snapshot"},
    "email": {"mode": "delta"},
    "calendar": {"mode": "delta"},
    "course_portal": {"mode": "delta"},
    "price_tracker": {
        "mode": "snapshot",
        "default_item": {
            "id": "price_status",
            "text": "Price check: item is $99.",
            "value": 99,
            "meta": {"currency": "USD"},
        },
    },
    "bank_balance": {
        "mode": "snapshot",
        "default_item": {
            "id": "balance_status",
            "text": "Balance check: $220.",
            "value": 220,
            "meta": {"currency": "USD"},
        },
    },
    "shipment_status": {
        "mode": "snapshot",
        "default_item": {
            "id": "shipment_status",
            "text": "Delivery status: no active shipment.",
            "value": None,
            "meta": {"phase": "idle"},
        },
    },
    "laundry_status": {
        "mode": "snapshot",
        "default_item": {
            "id": "laundry_status",
            "text": "Laundry status: idle.",
            "value": None,
            "meta": {"phase": "idle"},
        },
    },
    "library_hold": {"mode": "delta"},
    "reservation_waitlist": {"mode": "delta"},
    "appointment_portal": {"mode": "delta"},
}

PROCESS_CHANNELS = {"laundry_status", "shipment_status"}

ARCHETYPES = [
    {
        "name": "errand_heavy",
        "step_count": (10, 13),
        "blocks": {"pre11": (2, 3), "mid": (2, 4), "eve": (2, 3), "late": (0, 1)},
        "intro_mode": "agenda",
        "domains": ("errands", "health", "home", "delivery"),
        "tempo": "moving",
    },
    {
        "name": "meeting_heavy",
        "step_count": (11, 14),
        "blocks": {"pre11": (3, 4), "mid": (4, 5), "eve": (1, 2), "late": (0, 1)},
        "intro_mode": "notes",
        "domains": ("work", "admin", "delivery", "health"),
        "tempo": "packed",
    },
    {
        "name": "low_key",
        "step_count": (9, 10),
        "blocks": {"pre11": (2, 3), "mid": (2, 3), "eve": (1, 2), "late": (0, 1)},
        "intro_mode": "none",
        "domains": ("home", "social", "errands", "health"),
        "tempo": "calm",
    },
    {
        "name": "disruption",
        "step_count": (10, 13),
        "blocks": {"pre11": (2, 3), "mid": (3, 4), "eve": (2, 3), "late": (0, 1)},
        "intro_mode": "notes",
        "domains": ("disruptions", "work", "home", "errands"),
        "tempo": "interrupted",
    },
    {
        "name": "delivery_watchful",
        "step_count": (10, 12),
        "blocks": {"pre11": (2, 3), "mid": (3, 4), "eve": (1, 2), "late": (0, 1)},
        "intro_mode": "agenda",
        "domains": ("delivery", "home", "admin", "health"),
        "tempo": "watchful",
    },
    {
        "name": "admin_catchup",
        "step_count": (10, 12),
        "blocks": {"pre11": (2, 2), "mid": (4, 5), "eve": (1, 2), "late": (0, 1)},
        "intro_mode": "agenda",
        "domains": ("admin", "work", "health", "class"),
        "tempo": "stacked",
    },
    {
        "name": "social_outing",
        "step_count": (10, 13),
        "blocks": {"pre11": (2, 3), "mid": (2, 3), "eve": (3, 4), "late": (0, 1)},
        "intro_mode": "none",
        "domains": ("social", "errands", "delivery", "health"),
        "tempo": "social",
    },
    {
        "name": "class_learning",
        "step_count": (10, 12),
        "blocks": {"pre11": (2, 3), "mid": (3, 4), "eve": (2, 3), "late": (0, 1)},
        "intro_mode": "notes",
        "domains": ("class", "admin", "social", "health"),
        "tempo": "focused",
    },
    {
        "name": "mixed_logistics",
        "step_count": (10, 13),
        "blocks": {"pre11": (2, 3), "mid": (3, 4), "eve": (2, 3), "late": (0, 1)},
        "intro_mode": "agenda",
        "domains": ("home", "work", "errands", "delivery"),
        "tempo": "mixed",
    },
]

THREAD_LIBRARY = [
    {"id": "delivery_arc", "domains": ("delivery", "home"), "summary": "A few package and building-access details keep moving around."},
    {"id": "appointment_arc", "domains": ("health", "admin"), "summary": "A health appointment thread keeps resurfacing in small ways."},
    {"id": "class_arc", "domains": ("class", "admin"), "summary": "A class or workshop thread picks up and changes shape during the week."},
    {"id": "social_arc", "domains": ("social", "errands"), "summary": "A social plan keeps getting adjusted around other obligations."},
    {"id": "work_arc", "domains": ("work", "admin"), "summary": "A handful of work items keep shifting as the week fills up."},
    {"id": "home_arc", "domains": ("home", "delivery"), "summary": "Home logistics create a running background thread."},
    {"id": "errand_arc", "domains": ("errands", "health"), "summary": "A set of errands keeps producing follow-ups instead of resolving cleanly."},
]

PRE11_CANDIDATES = [
    "07:20", "07:35", "07:50", "08:05", "08:20", "08:40", "08:55",
    "09:10", "09:25", "09:40", "10:00", "10:20", "10:40",
]
MID_CANDIDATES = [
    "11:20", "11:35", "11:50", "12:10", "12:25", "12:45", "13:00",
    "13:20", "13:35", "13:55", "14:10", "14:30", "14:45", "15:05",
    "15:20", "15:40", "15:55", "16:15", "16:30", "16:50",
]
EVE_CANDIDATES = [
    "17:05", "17:25", "17:40", "18:00", "18:15", "18:35", "18:50",
    "19:10", "19:25", "19:45", "20:00", "20:20", "20:40",
]
LATE_CANDIDATES = ["21:20", "21:35", "21:55", "22:10", "22:30", "22:45"]

TIME_TASK_LIBRARY = [
    {"id_base": "send_budget_note", "domain": "work", "label_base": "Send the budget note", "bands": ("mid", "eve")},
    {"id_base": "check_in_manager", "domain": "work", "label_base": "Check in with your manager", "bands": ("mid",)},
    {"id_base": "call_insurance", "domain": "health", "label_base": "Call the insurance desk", "bands": ("mid",)},
    {"id_base": "review_course_outline", "domain": "class", "label_base": "Review the course outline", "bands": ("eve", "late")},
    {"id_base": "send_repair_photo", "domain": "home", "label_base": "Send the repair photo", "bands": ("mid", "eve")},
    {"id_base": "pay_parking_app", "domain": "errands", "label_base": "Pay the parking app balance", "bands": ("pre11", "mid")},
    {"id_base": "confirm_pickup_window", "domain": "delivery", "label_base": "Confirm the pickup window", "bands": ("mid", "eve")},
    {"id_base": "submit_timesheet", "domain": "admin", "label_base": "Submit the timesheet", "bands": ("mid", "eve")},
    {"id_base": "text_roommate", "domain": "social", "label_base": "Text your roommate about the plan", "bands": ("eve",)},
    {"id_base": "check_transit_times", "domain": "errands", "label_base": "Check the transit times", "bands": ("pre11", "mid")},
    {"id_base": "email_vendor", "domain": "admin", "label_base": "Email the vendor", "bands": ("mid",)},
    {"id_base": "review_lab_notes", "domain": "class", "label_base": "Review the lab notes", "bands": ("eve", "late")},
    {"id_base": "confirm_guest_count", "domain": "social", "label_base": "Confirm the guest count", "bands": ("mid", "eve")},
    {"id_base": "record_meter_reading", "domain": "home", "label_base": "Record the meter reading", "bands": ("eve",)},
    {"id_base": "pay_coop_dues", "domain": "admin", "label_base": "Pay the co-op dues", "bands": ("mid",)},
    {"id_base": "send_library_email", "domain": "errands", "label_base": "Send the library email", "bands": ("mid", "eve")},
    {"id_base": "draft_status_note", "domain": "work", "label_base": "Draft the status note", "bands": ("mid",)},
    {"id_base": "check_lab_portal", "domain": "class", "label_base": "Check the lab portal", "bands": ("mid", "eve")},
]

NARRATIVE_EVENTS = [
    {"id_base": "pharmacy_counter", "domain": "health", "dayparts": ("mid", "eve"), "display": "the pharmacy counter", "cue_line": "At the pharmacy, the pickup counter is finally open.", "task_label": "Pick up the prescription when you reach the pharmacy counter"},
    {"id_base": "clinic_window", "domain": "health", "dayparts": ("pre11", "mid"), "display": "the clinic check-in window", "cue_line": "The clinic check-in window is open when you pass it.", "task_label": "Ask about the referral when the clinic check-in window is open"},
    {"id_base": "lab_dropbox", "domain": "health", "dayparts": ("mid", "eve"), "display": "the lab drop box", "cue_line": "You notice the lab drop box is unlocked for afternoon drop-offs.", "task_label": "Drop off the sample slip when the lab drop box is unlocked"},
    {"id_base": "parking_receipt_kiosk", "domain": "health", "dayparts": ("pre11", "mid"), "display": "the parking receipt kiosk", "cue_line": "The parking receipt kiosk near the clinic is blinking again.", "task_label": "Print the parking receipt when the kiosk starts blinking"},
    {"id_base": "front_desk_clipboard", "domain": "health", "dayparts": ("mid",), "display": "the front desk clipboard", "cue_line": "A clipboard is waiting on the front desk with your name on it.", "task_label": "Sign the intake form when the front desk clipboard is out"},

    {"id_base": "hardware_counter", "domain": "errands", "dayparts": ("mid", "eve"), "display": "the hardware counter", "cue_line": "The hardware counter is finally clear enough to walk up to.", "task_label": "Pick up the replacement filter when the hardware counter clears"},
    {"id_base": "dry_cleaner_rack", "domain": "errands", "dayparts": ("mid", "eve"), "display": "the dry cleaner rack", "cue_line": "The dry cleaner has your order hanging on the front rack.", "task_label": "Collect the dry cleaning when it reaches the front rack"},
    {"id_base": "library_return_slot", "domain": "errands", "dayparts": ("eve",), "display": "the library return slot", "cue_line": "The library return slot is open as you walk by.", "task_label": "Return the library book when the return slot is open"},
    {"id_base": "grocery_pickup_shelf", "domain": "errands", "dayparts": ("mid", "eve"), "display": "the grocery pickup shelf", "cue_line": "The grocery pickup shelf has your bag set aside.", "task_label": "Grab the grocery bag when it appears on the pickup shelf"},
    {"id_base": "parcel_counter", "domain": "errands", "dayparts": ("mid",), "display": "the parcel counter", "cue_line": "The parcel counter has a line, but your package is visible behind it.", "task_label": "Collect the parcel when you reach the counter"},

    {"id_base": "manager_door", "domain": "work", "dayparts": ("mid",), "display": "your manager at the doorway", "cue_line": "Your manager pauses at the doorway on the way to another meeting.", "task_label": "Give the quick update when your manager stops at the doorway"},
    {"id_base": "conference_screen", "domain": "work", "dayparts": ("pre11", "mid"), "display": "the conference room screen", "cue_line": "The conference room screen flashes your room assignment.", "task_label": "Pick up the room key when the conference room screen flashes your room assignment"},
    {"id_base": "courier_desk", "domain": "work", "dayparts": ("mid",), "display": "the courier at the desk", "cue_line": "A courier is waiting at the reception desk with a slim envelope.", "task_label": "Sign for the envelope when the courier reaches the desk"},
    {"id_base": "printer_queue_light", "domain": "work", "dayparts": ("pre11",), "display": "the printer queue light", "cue_line": "The printer queue light is flashing near the shared workspace.", "task_label": "Collect the handouts when the printer queue light flashes"},
    {"id_base": "lobby_badge_reader", "domain": "work", "dayparts": ("pre11",), "display": "the lobby badge reader", "cue_line": "The lobby badge reader blinks yellow when you head back in.", "task_label": "Reset your badge when the lobby badge reader blinks yellow"},

    {"id_base": "laundry_room_cart", "domain": "home", "dayparts": ("eve",), "display": "the laundry room cart", "cue_line": "A laundry room cart is sitting empty near the door.", "task_label": "Bring down the blankets when the laundry room cart is free"},
    {"id_base": "building_mail_slot", "domain": "home", "dayparts": ("pre11", "mid"), "display": "the building mail slot", "cue_line": "The building mail slot is cracked open with a notice sticking out.", "task_label": "Take the notice when the building mail slot is cracked open"},
    {"id_base": "repair_van", "domain": "home", "dayparts": ("mid",), "display": "the repair van", "cue_line": "The repair van is parked outside earlier than expected.", "task_label": "Meet the technician when the repair van pulls up"},
    {"id_base": "storage_cage", "domain": "home", "dayparts": ("eve",), "display": "the storage cage", "cue_line": "The storage cage has been left open for deliveries again.", "task_label": "Bring upstairs the folded chair when the storage cage is open"},
    {"id_base": "roof_access_sign", "domain": "home", "dayparts": ("eve",), "display": "the roof access sign", "cue_line": "The roof access sign is temporarily uncovered while maintenance is there.", "task_label": "Take the photo of the leak note when the roof access sign is uncovered"},

    {"id_base": "cafe_patio_table", "domain": "social", "dayparts": ("eve",), "display": "the cafe patio table", "cue_line": "A patio table finally opens up at the cafe.", "task_label": "Hand over the spare charger when you get a patio table"},
    {"id_base": "friend_bike_rack", "domain": "social", "dayparts": ("eve",), "display": "your friend's bike at the rack", "cue_line": "Your friend's bike is already locked at the rack outside.", "task_label": "Drop off the tote bag when you spot your friend's bike at the rack"},
    {"id_base": "community_board", "domain": "social", "dayparts": ("mid", "eve"), "display": "the community bulletin board", "cue_line": "The community bulletin board has a fresh note pinned up.", "task_label": "Check the meetup note when the community bulletin board is updated"},
    {"id_base": "courtyard_bench", "domain": "social", "dayparts": ("eve",), "display": "the courtyard bench", "cue_line": "The courtyard bench is finally empty for a minute.", "task_label": "Leave the borrowed book when the courtyard bench is free"},
    {"id_base": "studio_lobby", "domain": "social", "dayparts": ("eve",), "display": "the studio lobby", "cue_line": "The studio lobby lights are on early tonight.", "task_label": "Drop off the poster tube when the studio lobby lights come on"},

    {"id_base": "campus_board", "domain": "class", "dayparts": ("pre11", "mid"), "display": "the campus notice board", "cue_line": "A fresh notice is pinned to the campus board outside the lab.", "task_label": "Photograph the room change when the campus notice board is updated"},
    {"id_base": "lab_cubby", "domain": "class", "dayparts": ("mid",), "display": "the lab cubby", "cue_line": "Your lab cubby has the handout packet tucked inside it.", "task_label": "Pick up the handout packet when it shows up in the lab cubby"},
    {"id_base": "seminar_sign", "domain": "class", "dayparts": ("mid",), "display": "the seminar sign", "cue_line": "The seminar sign has today's room scribbled in the corner.", "task_label": "Confirm the room number when the seminar sign is updated"},
    {"id_base": "studio_supply_table", "domain": "class", "dayparts": ("eve",), "display": "the studio supply table", "cue_line": "The studio supply table has the loaner kit set out.", "task_label": "Pick up the loaner kit when it appears on the supply table"},
    {"id_base": "lecture_side_door", "domain": "class", "dayparts": ("mid",), "display": "the lecture hall side door", "cue_line": "The lecture hall side door is propped open while the room resets.", "task_label": "Tape up the notice when the lecture hall side door is propped open"},

    {"id_base": "package_locker_light", "domain": "delivery", "dayparts": ("eve",), "display": "the package locker light", "cue_line": "The package locker light is finally green instead of red.", "task_label": "Collect the package when the locker light turns green"},
    {"id_base": "doorbell_camera_flash", "domain": "delivery", "dayparts": ("mid", "eve"), "display": "the doorbell camera flash", "cue_line": "The doorbell camera flashes while you're still nearby.", "task_label": "Buzz in the courier when the doorbell camera flashes"},
    {"id_base": "loading_dock_sign", "domain": "delivery", "dayparts": ("mid",), "display": "the loading dock sign", "cue_line": "The loading dock sign is pointing to a temporary pickup spot today.", "task_label": "Ask about the boxed lamp when the loading dock sign points to pickup"},
    {"id_base": "mailroom_shelf", "domain": "delivery", "dayparts": ("mid",), "display": "the mailroom shelf", "cue_line": "A tube-shaped package is sitting alone on the mailroom shelf.", "task_label": "Pick up the poster tube when it reaches the mailroom shelf"},
    {"id_base": "concierge_counter", "domain": "delivery", "dayparts": ("eve",), "display": "the concierge counter", "cue_line": "The concierge counter has your oversized parcel tag clipped to the side.", "task_label": "Ask for the oversized parcel when the tag appears at the concierge counter"},

    {"id_base": "detour_arrow", "domain": "disruptions", "dayparts": ("pre11", "mid"), "display": "the detour arrow", "cue_line": "A temporary detour arrow sends you along the side entrance.", "task_label": "Check the posted hours when the detour arrow sends you to the side entrance"},
    {"id_base": "elevator_notice", "domain": "disruptions", "dayparts": ("mid", "eve"), "display": "the elevator notice", "cue_line": "An elevator notice is taped up where the call button usually lights up.", "task_label": "Take the stairwell parcel when the elevator notice is posted"},
    {"id_base": "rain_canopy", "domain": "disruptions", "dayparts": ("eve",), "display": "the rain canopy", "cue_line": "A rain canopy has been dragged over the sidewalk entrance.", "task_label": "Collect the folding umbrella when the rain canopy is up"},
    {"id_base": "service_gate", "domain": "disruptions", "dayparts": ("mid",), "display": "the service gate", "cue_line": "The service gate is open for a short maintenance window.", "task_label": "Leave the return crate when the service gate is open"},
    {"id_base": "backup_generator", "domain": "disruptions", "dayparts": ("eve",), "display": "the backup generator cart", "cue_line": "A backup generator cart is parked near the side path again.", "task_label": "Photograph the serial plate when the generator cart is parked outside"},
]

STATE_EVENT_LIBRARY = [
    {"id_base": "email_form_followup", "domain": "admin", "channel": "email", "dayparts": ("mid",), "label": "Reply to the follow-up form email when it arrives", "text": "New email: follow-up form is ready."},
    {"id_base": "email_receipt_note", "domain": "errands", "channel": "email", "dayparts": ("eve",), "label": "Save the receipt when the confirmation email arrives", "text": "New email: purchase confirmation received."},
    {"id_base": "email_vendor_reply", "domain": "work", "channel": "email", "dayparts": ("mid",), "label": "Forward the vendor reply when the email lands", "text": "New email: vendor sent the updated reply."},
    {"id_base": "calendar_room_shift", "domain": "work", "channel": "calendar", "dayparts": ("pre11", "mid"), "label": "Adjust the prep plan when the calendar room shift appears", "text": "Calendar update: room changed for this afternoon."},
    {"id_base": "calendar_call_move", "domain": "work", "channel": "calendar", "dayparts": ("mid",), "label": "Move the check-in when the calendar update moves the call", "text": "Calendar update: check-in moved later today."},
    {"id_base": "calendar_new_block", "domain": "admin", "channel": "calendar", "dayparts": ("mid",), "label": "Add the new block when it appears on your calendar", "text": "Calendar update: new block added for today."},
    {"id_base": "calendar_guest_note", "domain": "social", "channel": "calendar", "dayparts": ("eve",), "label": "Adjust the meetup note when the calendar guest count changes", "text": "Calendar update: guest count changed for tonight."},
    {"id_base": "course_assignment_posted", "domain": "class", "channel": "course_portal", "dayparts": ("mid",), "label": "Start the assignment when it posts on the course portal", "text": "Course portal: assignment posted."},
    {"id_base": "course_discussion_open", "domain": "class", "channel": "course_portal", "dayparts": ("eve",), "label": "Open the discussion thread when it unlocks", "text": "Course portal: discussion thread unlocked."},
    {"id_base": "course_grade_released", "domain": "class", "channel": "course_portal", "dayparts": ("mid",), "label": "Check the grade when it is released", "text": "Course portal: grade released."},
    {"id_base": "price_drop_54", "domain": "home", "channel": "price_tracker", "dayparts": ("eve",), "label": "Buy the filter when the price drops below $55", "text": "Price check: filter is $54.", "value": 54, "meta": {"currency": "USD"}},
    {"id_base": "price_drop_72", "domain": "home", "channel": "price_tracker", "dayparts": ("eve",), "label": "Buy the storage bin when the price drops below $75", "text": "Price check: storage bin is $72.", "value": 72, "meta": {"currency": "USD"}},
    {"id_base": "price_drop_39", "domain": "class", "channel": "price_tracker", "dayparts": ("eve",), "label": "Buy the workbook when the price drops below $40", "text": "Price check: workbook is $39.", "value": 39, "meta": {"currency": "USD"}},
    {"id_base": "balance_low_140", "domain": "admin", "channel": "bank_balance", "dayparts": ("mid", "eve"), "label": "Transfer money when the balance drops below $140", "text": "Balance check: $138.", "value": 138, "meta": {"currency": "USD"}},
    {"id_base": "balance_low_95", "domain": "admin", "channel": "bank_balance", "dayparts": ("mid", "eve"), "label": "Move money when the balance drops below $95", "text": "Balance check: $92.", "value": 92, "meta": {"currency": "USD"}},
    {"id_base": "balance_low_68", "domain": "social", "channel": "bank_balance", "dayparts": ("eve",), "label": "Transfer funds when the balance drops below $70", "text": "Balance check: $68.", "value": 68, "meta": {"currency": "USD"}},
    {"id_base": "library_hold_ready", "domain": "errands", "channel": "library_hold", "dayparts": ("eve",), "label": "Pick up the hold when the library notice says it is ready", "text": "Library notice: your hold is ready."},
    {"id_base": "library_hold_second_ready", "domain": "class", "channel": "library_hold", "dayparts": ("eve",), "label": "Collect the reserve reading when the library hold is ready", "text": "Library notice: reserve reading is ready."},
    {"id_base": "reservation_slot_open", "domain": "social", "channel": "reservation_waitlist", "dayparts": ("eve",), "label": "Accept the reservation when the waitlist opens a slot", "text": "Waitlist update: a table is available."},
    {"id_base": "reservation_counter_offer", "domain": "social", "channel": "reservation_waitlist", "dayparts": ("eve",), "label": "Respond when the waitlist sends a counteroffer", "text": "Waitlist update: earlier seating is available."},
    {"id_base": "appointment_slot_open", "domain": "health", "channel": "appointment_portal", "dayparts": ("mid",), "label": "Book the appointment when a slot opens in the portal", "text": "Appointment portal: a slot opened."},
    {"id_base": "appointment_reschedule_open", "domain": "health", "channel": "appointment_portal", "dayparts": ("mid",), "label": "Move the appointment when a better slot opens", "text": "Appointment portal: earlier slot available."},
    {"id_base": "appointment_form_ready", "domain": "health", "channel": "appointment_portal", "dayparts": ("mid",), "label": "Finish the intake form when the portal posts it", "text": "Appointment portal: intake form posted."},
    {"id_base": "shipment_out_for_delivery", "domain": "delivery", "channel": "shipment_status", "process": True, "label": "Be home when the delivery is out for delivery", "start_text": "Delivery status: in transit.", "start_narrative": "You glance at tracking again while you're between tasks.", "complete_text": "Delivery status: out for delivery."},
    {"id_base": "laundry_done", "domain": "home", "channel": "laundry_status", "process": True, "label": "Move the laundry when the cycle ends", "start_text": "Laundry status: in progress.", "start_narrative": "You start a laundry cycle before you leave it alone.", "complete_text": "Laundry status: cycle complete."},
]

LURE_LIBRARY = [
    {"id": "skim_headlines", "action_text": "Skim the headlines."},
    {"id": "wipe_counter", "action_text": "Wipe down the counter."},
    {"id": "sort_mail", "action_text": "Sort the mail."},
    {"id": "charge_phone", "action_text": "Charge your phone."},
    {"id": "water_plants", "action_text": "Water the plants."},
    {"id": "clear_desk", "action_text": "Clear off the desk."},
    {"id": "text_friend", "action_text": "Send a quick text to a friend."},
    {"id": "brew_tea", "action_text": "Make a cup of tea."},
    {"id": "scan_receipts", "action_text": "Scan the loose receipts."},
    {"id": "fold_sweater", "action_text": "Fold the sweater on the chair."},
    {"id": "refill_bottle", "action_text": "Refill your water bottle."},
    {"id": "reply_group_chat", "action_text": "Reply in the group chat."},
    {"id": "archive_photos", "action_text": "Archive a few photos."},
    {"id": "rearrange_books", "action_text": "Rearrange the stack of books."},
    {"id": "clean_keyboard", "action_text": "Clean the keyboard."},
    {"id": "browse_menu", "action_text": "Browse a dinner menu."},
    {"id": "check_weather", "action_text": "Check the weather."},
    {"id": "put_away_dishes", "action_text": "Put away the dishes."},
    {"id": "sharpen_pencils", "action_text": "Sharpen a few pencils."},
    {"id": "straighten_couch", "action_text": "Straighten the couch pillows."},
    {"id": "look_up_recipe", "action_text": "Look up a recipe."},
    {"id": "review_notes", "action_text": "Review your notes."},
    {"id": "switch_laundry", "action_text": "Switch over the laundry basket."},
    {"id": "trim_receipt_stack", "action_text": "Trim the receipt stack."},
    {"id": "call_friend", "action_text": "Call a friend."},
    {"id": "look_at_map", "action_text": "Look at the map."},
    {"id": "tidy_entryway", "action_text": "Tidy the entryway."},
    {"id": "plug_in_tablet", "action_text": "Plug in the tablet."},
    {"id": "organize_bag", "action_text": "Organize your bag."},
    {"id": "clean_mug", "action_text": "Clean the mug in the sink."},
    {"id": "stretch_break", "action_text": "Take a short stretch break."},
    {"id": "queue_playlist", "action_text": "Queue up a playlist."},
    {"id": "read_blurb", "action_text": "Read a book blurb."},
    {"id": "order_snack", "action_text": "Order a snack."},
    {"id": "clear_downloads", "action_text": "Clear old downloads."},
    {"id": "check_transfers", "action_text": "Check your saved transfers."},
    {"id": "label_folder", "action_text": "Label a folder."},
    {"id": "wipe_glasses", "action_text": "Wipe your glasses."},
    {"id": "scan_calendar", "action_text": "Scan your calendar."},
    {"id": "move_blanket", "action_text": "Move the blanket off the chair."},
]

CROSS_DAY_ACTIONS = {
    "health": [
        "bring the insurance card",
        "bring the referral slip",
        "carry the prescription receipt",
        "bring the lab form",
    ],
    "errands": [
        "bring the return receipt",
        "carry the spare tote bag",
        "bring the extra hanger set",
        "bring the library receipt",
    ],
    "work": [
        "email the room note",
        "bring the printed handouts",
        "forward the staffing note",
        "carry the signed form",
    ],
    "home": [
        "bring down the spare linens",
        "take the meter photo",
        "bring up the folding chair",
        "carry the repair note",
    ],
    "social": [
        "bring the borrowed book",
        "leave the charger",
        "bring the extra mug",
        "bring the printed invite",
    ],
    "class": [
        "bring the reserve reading",
        "carry the lab handout",
        "email the room change note",
        "bring the poster tube",
    ],
    "delivery": [
        "bring the pickup code",
        "leave the doorman note",
        "carry the return label",
        "bring the parcel slip",
    ],
    "disruptions": [
        "bring the umbrella",
        "take the detour photo",
        "carry the side-door note",
        "bring the backup key",
    ],
}

CROSS_DAY_ACTIONS_BY_FAMILY = {
    "friend_bike_rack": [
        "bring the borrowed book",
        "leave the charger",
        "return the spare key",
    ],
    "cafe_patio_table": [
        "bring the extra mug",
        "pass along the note envelope",
        "leave the charger",
    ],
    "laundry_room_cart": [
        "bring down the spare linens",
        "bring down the blankets",
        "carry the laundry soap",
    ],
    "building_mail_slot": [
        "bring up the folding chair",
        "bring the return envelope",
        "carry the spare key",
    ],
    "library_return_slot": [
        "carry the spare tote bag",
        "bring the due-date slip",
        "bring the book band",
    ],
    "studio_lobby": [
        "bring the poster tube",
        "leave the charger",
        "bring the borrowed book",
    ],
    "pharmacy_counter": [
        "bring the referral slip",
        "bring the insurance card",
        "carry the prescription receipt",
    ],
}

CROSS_DAY_BLOCKED_FAMILIES = {
    "roof_access_sign",
}

OVERRIDE_DISPLAY_LIBRARY = [
    (
        "the follow-up text",
        "A follow-up text comes in with the final location.",
    ),
    (
        "the confirmation email",
        "A confirmation email comes in with the final details.",
    ),
    (
        "the note by the side door",
        "A note by the side door clears up where to go.",
    ),
    (
        "the updated pickup message",
        "An updated pickup message comes through with the final details.",
    ),
    (
        "the voicemail from the front desk",
        "A voicemail from the front desk clears up what to look for.",
    ),
]

OPTION_POOLS = [
    ["A) Pour coffee", "B) Open a note", "C) Check the window"],
    ["A) Reply quickly", "B) Keep walking", "C) Put the phone away"],
    ["A) Fill a bottle", "B) Look around", "C) Keep moving"],
    ["A) Stack papers", "B) Take a breath", "C) Check the time"],
    ["A) Order lunch", "B) Sit down", "C) Tidy your bag"],
    ["A) Open the app", "B) Flag it for later", "C) Keep your place in line"],
    ["A) Step outside", "B) Stretch your shoulders", "C) Read the sign"],
    ["A) Clear a spot", "B) Lean on the counter", "C) Check your messages"],
    ["A) Pull up a list", "B) Take a sip of water", "C) Look for a pen"],
    ["A) Make a note", "B) Adjust your bag", "C) Wait a moment"],
    ["A) Start dinner", "B) Put a pan on", "C) Rinse vegetables"],
    ["A) Brush your teeth", "B) Read a page", "C) Plug in your phone"],
    ["A) Stand up", "B) Walk once around the room", "C) Refill your mug"],
    ["A) Scan the shelf", "B) Look up", "C) Check your pocket"],
]

VISIBLE_CUE_IDS = {"breakfast", "dinner"}

SCENE_FOCUS_BY_DOMAIN = {
    "health": [
        "the insurance card",
        "the referral slip",
        "the pharmacy receipt",
        "the appointment note",
    ],
    "errands": [
        "the tote bag",
        "the receipt stack",
        "the library slip",
        "the pickup receipt",
    ],
    "work": [
        "the printed handout",
        "the room note",
        "the badge",
        "the draft on your screen",
    ],
    "home": [
        "the spare key",
        "the laundry bag",
        "the folded towel",
        "the repair note",
    ],
    "social": [
        "the charger",
        "the borrowed book",
        "the message thread",
        "the extra mug",
    ],
    "class": [
        "the handout packet",
        "the workbook",
        "the room note",
        "the reserve reading",
    ],
    "delivery": [
        "the pickup code",
        "the parcel slip",
        "the tracking page",
        "the return label",
    ],
    "disruptions": [
        "the umbrella",
        "the side-door note",
        "the detour photo",
        "the backup key",
    ],
}


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def sentence_case(text):
    if not text:
        return text
    return text[0].upper() + text[1:]


def lower_first(text):
    if not text:
        return text
    return text[0].lower() + text[1:]


def ensure_period(text):
    text = text.strip()
    if text.endswith("."):
        return text
    return f"{text}."


def join_sentences(parts):
    return " ".join(ensure_period(part) for part in parts if part).strip()


def time_to_minutes_local(value):
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def minutes_to_time(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def replace_terminal_time(label, new_time):
    cleaned = (label or "").strip().rstrip(".")
    if re.search(r"\s+(at|around)\s+\d{1,2}:\d{2}$", cleaned, flags=re.IGNORECASE):
        return re.sub(
            r"\s+(at|around)\s+\d{1,2}:\d{2}$",
            f" at {new_time}",
            cleaned,
            flags=re.IGNORECASE,
        )
    return f"{cleaned} at {new_time}"


def base_task_label(label):
    cleaned = (label or "").strip().rstrip(".")
    cleaned = re.sub(r"\s+(at|around)\s+\d{1,2}:\d{2}$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+when\s+.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def derive_action_text_from_label(label):
    text = (label or "").strip().rstrip(".")
    if not text:
        return "Do the task."
    text = re.sub(r"\s+when\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(at|around)\s+\d{1,2}:\d{2}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return ensure_period(sentence_case(text))


def action_gerund_from_label(label):
    text = lower_first(base_task_label(label))
    replacements = [
        ("hand over ", "handing over "),
        ("pick up ", "picking up "),
        ("drop off ", "dropping off "),
        ("check in with ", "checking in with "),
        ("sign for ", "signing for "),
        ("pay ", "paying "),
        ("send ", "sending "),
        ("text ", "texting "),
        ("email ", "emailing "),
        ("call ", "calling "),
        ("review ", "reviewing "),
        ("confirm ", "confirming "),
        ("record ", "recording "),
        ("bring ", "bringing "),
        ("leave ", "leaving "),
        ("return ", "returning "),
        ("collect ", "collecting "),
        ("print ", "printing "),
        ("buy ", "buying "),
        ("move ", "moving "),
        ("check ", "checking "),
        ("ask ", "asking "),
        ("meet ", "meeting "),
        ("take ", "taking "),
        ("grab ", "grabbing "),
        ("forward ", "forwarding "),
        ("give ", "giving "),
        ("add ", "adding "),
        ("adjust ", "adjusting "),
        ("accept ", "accepting "),
        ("respond ", "responding "),
        ("transfer ", "transferring "),
        ("finish ", "finishing "),
        ("book ", "booking "),
        ("buzz in ", "buzzing in "),
        ("tape up ", "taping up "),
        ("photograph ", "photographing "),
        ("reset ", "resetting "),
    ]
    for source, target in replacements:
        if text.startswith(source):
            return target + text[len(source):]
    first, _, rest = text.partition(" ")
    if not rest:
        return f"{first}ing"
    return f"{first}ing {rest}"


def disambiguate_day_action_texts(tasks):
    by_text = {}
    for task in tasks:
        action_text = (task.get("action_text") or "").strip()
        if not action_text:
            continue
        by_text.setdefault(action_text.lower(), []).append(task)
    for group in by_text.values():
        if len(group) <= 1:
            continue
        for task in group:
            base = task["action_text"].rstrip(".")
            target_time = task.get("target_time")
            cue_id = task.get("cue_id")
            if target_time:
                task["action_text"] = ensure_period(f"{base} at {target_time}")
            elif cue_id:
                cue_hint = re.sub(r"_d\d+\b", "", cue_id).replace("_", " ").strip()
                task["action_text"] = ensure_period(f"{base} when you notice {cue_hint}")
            else:
                task["action_text"] = ensure_period(f"{base} ({task['id']})")
    seen = {}
    for task in tasks:
        seen.setdefault(task["action_text"].lower(), []).append(task)
    for group in seen.values():
        if len(group) <= 1:
            continue
        for index, task in enumerate(sorted(group, key=lambda item: item["id"]), start=1):
            task["action_text"] = ensure_period(f"{task['action_text'].rstrip('.')} ({index})")


def override_label(label, display):
    cleaned = (label or "").strip().rstrip(".")
    if "text" in display or "message" in display:
        replacement = f" when {display} comes in"
    elif "email" in display or "voicemail" in display:
        replacement = f" when {display} arrives"
    else:
        replacement = f" when you notice {display}"
    if " when " in cleaned.lower():
        return re.sub(
            r"\s+when\s+.*$",
            replacement,
            cleaned,
            flags=re.IGNORECASE,
        )
    return f"{cleaned}{replacement}"


def split_sentences(text):
    if not text:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def choice_with_fallback(rng, pool, used_sentences=None):
    items = list(pool)
    rng.shuffle(items)
    if used_sentences is None:
        return items[0]
    for item in items:
        if item not in used_sentences:
            used_sentences.add(item)
            return item
    used_sentences.add(items[0])
    return items[0]


def phase_for_time(time_text):
    minutes = time_to_minutes_local(time_text)
    if minutes < 11 * 60:
        return "pre11"
    if minutes < 17 * 60:
        return "mid"
    if minutes < 21 * 60:
        return "eve"
    return "late"


def choose_block_counts(archetype, step_count, rng):
    extra = step_count - 2
    blocks = {}
    total_min = 0
    total_max = 0
    for block_name, (min_count, max_count) in archetype["blocks"].items():
        blocks[block_name] = min_count
        total_min += min_count
        total_max += max_count
    if not total_min <= extra <= total_max:
        raise ValueError(f"Archetype {archetype['name']} cannot fit {step_count} steps")
    remaining = extra - total_min
    block_names = list(archetype["blocks"])
    while remaining > 0:
        candidates = [
            name for name in block_names
            if blocks[name] < archetype["blocks"][name][1]
        ]
        chosen = rng.choice(candidates)
        blocks[chosen] += 1
        remaining -= 1
    return blocks


def generate_day_times(archetype, rng, used_signatures):
    for _ in range(300):
        step_count = rng.randint(*archetype["step_count"])
        block_counts = choose_block_counts(archetype, step_count, rng)
        pre = sorted(rng.sample(PRE11_CANDIDATES, k=block_counts["pre11"]))
        mid = sorted(rng.sample(MID_CANDIDATES, k=block_counts["mid"]))
        eve = sorted(rng.sample(EVE_CANDIDATES, k=block_counts["eve"]))
        late = sorted(rng.sample(LATE_CANDIDATES, k=block_counts["late"]))
        times = pre + ["11:00"] + mid + eve + ["21:00"] + late
        signature = tuple(times)
        non_round = sum(1 for time_text in times if not time_text.endswith(":00"))
        if signature in used_signatures or non_round < 4:
            continue
        used_signatures.add(signature)
        return times
    raise RuntimeError(f"Unable to generate unique time signature for {archetype['name']}")


def normalize_family_id(identifier):
    return re.sub(r"_d\d+\b", "", identifier or "")


def select_templates(pool, domains, count, rng, used_ids=None):
    candidates = [item for item in pool if item["domain"] in domains]
    if used_ids:
        preferred = [item for item in candidates if item["id_base"] not in used_ids]
        if len(preferred) >= count:
            candidates = preferred
    rng.shuffle(candidates)
    selected = []
    seen = set()
    for item in candidates:
        if item["id_base"] in seen:
            continue
        selected.append(deepcopy(item))
        seen.add(item["id_base"])
        if len(selected) == count:
            break
    return selected


def unique_task_id(base, day_index):
    return f"{base}_d{day_index}"


def build_steps(day_index, times):
    steps = []
    for step_index, time_text in enumerate(times, start=1):
        steps.append(
            {
                "id": f"d{day_index}_s{step_index}",
                "time": time_text,
                "text": "",
                "options": deepcopy(OPTION_POOLS[(step_index - 1) % len(OPTION_POOLS)]),
                "cues": [],
                "updates": [],
                "_visible_cues": [],
                "_hidden_lines": [],
                "_notes": [],
                "_phase": phase_for_time(time_text),
            }
        )
    return steps


def first_step_for_phase(steps, phase_name, reverse=False):
    matching = [step for step in steps if step["_phase"] == phase_name]
    if not matching:
        return None
    return matching[-1] if reverse else matching[0]


def choose_step_for_dayparts(steps, dayparts, rng, occupied=None, reverse=False):
    occupied = occupied or set()
    candidates = [step for step in steps if step["_phase"] in dayparts and step["id"] not in occupied]
    if not candidates:
        candidates = [step for step in steps if step["_phase"] in dayparts]
    if not candidates:
        return None
    if reverse:
        candidates = list(reversed(candidates))
    return rng.choice(candidates)


def add_visible_cue(day_ctx, step, cue_id, sentence, display, family, domain):
    step["cues"].append(cue_id)
    step["_visible_cues"].append(sentence)
    day_ctx["_cue_index"][cue_id] = {
        "step_id": step["id"],
        "display": display,
        "family": family,
        "domain": domain,
        "channel": "narrative",
    }

def add_state_event(day_ctx, step, channel, event_id, text, domain, meta=None):
    step.setdefault("state_events", {}).setdefault(channel, []).append(
        {
            "id": event_id,
            "text": text,
            "value": None if meta is None else meta.get("value"),
            "meta": {} if meta is None else meta.get("meta", {}),
        }
    )
    day_ctx["_cue_index"][event_id] = {
        "step_id": step["id"],
        "display": text,
        "family": normalize_family_id(event_id),
        "domain": domain,
        "channel": channel,
    }


def add_task(tasks, payload):
    payload = deepcopy(payload)
    if "action_text" not in payload:
        payload["action_text"] = derive_action_text_from_label(payload["label"])
    tasks.append(payload)
    return payload


def add_regular_tasks(day_ctx, breakfast_step, dinner_step):
    tasks = day_ctx["tasks"]
    add_visible_cue(day_ctx, breakfast_step, "breakfast", "", "breakfast", "breakfast", "home")
    add_visible_cue(day_ctx, dinner_step, "dinner", "", "dinner", "dinner", "home")
    add_task(
        tasks,
        {
            "id": "antibiotic_breakfast",
            "label": "Take antibiotic at breakfast",
            "type": "event",
            "cue_id": "breakfast",
            "regular": True,
            "encoding": "start",
        },
    )
    add_task(
        tasks,
        {
            "id": "antibiotic_dinner",
            "label": "Take antibiotic at dinner",
            "type": "event",
            "cue_id": "dinner",
            "regular": True,
            "encoding": "start",
        },
    )
    add_task(
        tasks,
        {
            "id": "asthma_1100",
            "label": "Take asthma medication at 11:00",
            "type": "time",
            "target_time": "11:00",
            "regular": True,
            "encoding": "start",
        },
    )
    add_task(
        tasks,
        {
            "id": "asthma_2100",
            "label": "Take asthma medication at 21:00",
            "type": "time",
            "target_time": "21:00",
            "regular": True,
            "encoding": "start",
        },
    )


def choose_domains(archetype, thread_domains, rng):
    base = list(archetype["domains"])
    active_threads = [domain for domain in thread_domains if domain in base]
    if len(active_threads) >= 2:
        return tuple(rng.sample(active_threads, k=2) + [rng.choice(base)])
    blended = list(dict.fromkeys(active_threads + base))
    rng.shuffle(blended)
    return tuple(blended[:3])


def choose_intro_step(steps, target_time, rng):
    target_minutes = time_to_minutes_local(target_time)
    earlier = [step for step in steps if time_to_minutes_local(step["time"]) < target_minutes]
    if not earlier:
        return steps[0]
    return choose_light_step(earlier, rng)


def step_load(step):
    state_count = sum(len(items) for items in step.get("state_events", {}).values())
    return (
        len(step.get("_visible_cues", []))
        + len(step.get("_hidden_lines", []))
        + len(step.get("_notes", []))
        + len(step.get("updates", []))
        + state_count
    )


def choose_light_step(candidates, rng, avoid_meal=True):
    filtered = list(candidates)
    if avoid_meal:
        no_meal = [
            step for step in filtered
            if "breakfast" not in step.get("cues", []) and "dinner" not in step.get("cues", [])
        ]
        if no_meal:
            filtered = no_meal
    if not filtered:
        filtered = list(candidates)
    min_load = min(step_load(step) for step in filtered)
    lightest = [step for step in filtered if step_load(step) == min_load]
    return rng.choice(lightest)


def choose_update_source_step(steps, due_time, rng):
    due_minutes = time_to_minutes_local(due_time)
    earlier = [step for step in steps if time_to_minutes_local(step["time"]) < due_minutes]
    if not earlier:
        return None
    preferred = [
        step for step in earlier
        if not step.get("updates")
        and len(step.get("_notes", [])) < 2
        and "breakfast" not in step.get("cues", [])
        and "dinner" not in step.get("cues", [])
    ]
    if preferred:
        return choose_light_step(preferred, rng, avoid_meal=False)
    return choose_light_step(earlier, rng)


def build_day_context(
    day_index,
    day_name,
    archetype,
    thread_domains,
    rng,
    used_time_signatures,
    used_event_ids,
    used_time_task_ids,
):
    times = generate_day_times(archetype, rng, used_time_signatures)
    steps = build_steps(day_index, times)
    breakfast_step = first_step_for_phase(steps, "pre11")
    dinner_step = first_step_for_phase(steps, "eve", reverse=True)
    if breakfast_step is None or dinner_step is None:
        raise RuntimeError(f"Missing breakfast or dinner step for {day_name}")

    day_ctx = {
        "name": day_name,
        "archetype": archetype["name"],
        "start_instructions": [],
        "tasks": [],
        "lures": [],
        "steps": steps,
        "_cue_index": {},
        "_domains": choose_domains(archetype, thread_domains, rng),
        "_story_notes": [],
    }
    add_regular_tasks(day_ctx, breakfast_step, dinner_step)

    occupied_steps = {breakfast_step["id"], dinner_step["id"]}
    event_count = rng.randint(2, 4)
    events = select_templates(NARRATIVE_EVENTS, day_ctx["_domains"], event_count, rng, used_ids=used_event_ids)
    for template in events:
        step = choose_step_for_dayparts(day_ctx["steps"], template["dayparts"], rng, occupied=occupied_steps)
        if step is None:
            continue
        occupied_steps.add(step["id"])
        task_id = unique_task_id(template["id_base"], day_index)
        cue_id = task_id
        add_visible_cue(
            day_ctx,
            step,
            cue_id,
            template["cue_line"],
            template["display"],
            template["id_base"],
            template["domain"],
        )
        encoding = "start" if archetype["intro_mode"] == "agenda" or step["_phase"] == "pre11" else f"step:{step['id']}"
        add_task(
            day_ctx["tasks"],
            {
                "id": task_id,
                "label": template["task_label"],
                "type": "event",
                "cue_id": cue_id,
                "regular": False,
                "encoding": encoding,
            },
        )
        used_event_ids.add(template["id_base"])

    time_count = rng.randint(1, 2)
    time_templates = select_templates(TIME_TASK_LIBRARY, day_ctx["_domains"], time_count, rng, used_ids=used_time_task_ids)
    non_anchor_times = [step["time"] for step in day_ctx["steps"] if step["time"] not in ("11:00", "21:00")]
    for index, template in enumerate(time_templates, start=1):
        candidate_steps = [step for step in day_ctx["steps"] if step["_phase"] in template["bands"] and step["time"] in non_anchor_times]
        if not candidate_steps:
            candidate_steps = [step for step in day_ctx["steps"] if step["time"] in non_anchor_times]
        target_step = rng.choice(candidate_steps)
        label = f"{template['label_base']} at {target_step['time']}"
        task = add_task(
            day_ctx["tasks"],
            {
                "id": unique_task_id(f"{template['id_base']}_{index}", day_index),
                "label": label,
                "type": "time",
                "target_time": target_step["time"],
                "regular": False,
                "encoding": "start" if archetype["intro_mode"] == "agenda" else f"step:{choose_intro_step(day_ctx['steps'], target_step['time'], rng)['id']}",
                "_domain": template["domain"],
            },
        )
        intro_step = choose_intro_step(day_ctx["steps"], target_step["time"], rng)
        intro_step["_notes"].append(
            ensure_period(
                choice_with_fallback(
                    rng,
                    [
                        f"You still need to {lower_first(base_task_label(task['label']))} later.",
                        f"You make a mental note to {lower_first(base_task_label(task['label']))} before the day gets away from you.",
                        f"You don't want to forget to {lower_first(base_task_label(task['label']))}.",
                        f"You keep {lower_first(base_task_label(task['label']))} in the back of your mind.",
                        f"You mean to {lower_first(base_task_label(task['label']))} once things settle down.",
                        f"You keep telling yourself to {lower_first(base_task_label(task['label']))} before too long.",
                        f"You keep meaning to {lower_first(base_task_label(task['label']))}.",
                        f"You know you still have to {lower_first(base_task_label(task['label']))} today.",
                    ],
                )
            )
        )
        used_time_task_ids.add(template["id_base"])

    state_count = rng.randint(1, 3)
    state_templates = select_templates(STATE_EVENT_LIBRARY, day_ctx["_domains"], state_count, rng)
    for template in state_templates:
        if template.get("process"):
            if template["channel"] == "laundry_status":
                start_step = choose_step_for_dayparts(day_ctx["steps"], ("pre11",), rng)
                if start_step is None:
                    continue
                complete_candidates = [
                    step for step in day_ctx["steps"]
                    if time_to_minutes_local(step["time"]) > time_to_minutes_local(start_step["time"])
                ]
                complete_step = choose_step_for_dayparts(complete_candidates, ("eve", "late"), rng)
            else:
                start_candidates = [
                    step for step in day_ctx["steps"]
                    if step["_phase"] in {"pre11", "mid"} and time_to_minutes_local(step["time"]) <= time_to_minutes_local("15:40")
                ]
                if not start_candidates:
                    continue
                start_step = rng.choice(start_candidates)
                complete_candidates = [
                    step for step in day_ctx["steps"]
                    if time_to_minutes_local(start_step["time"]) < time_to_minutes_local(step["time"]) <= time_to_minutes_local("17:40")
                ]
                if not complete_candidates:
                    continue
                complete_step = rng.choice(complete_candidates)
            if start_step is None or complete_step is None:
                continue
            trigger_id = unique_task_id(template["id_base"], day_index)
            start_id = unique_task_id(f"{template['id_base']}_start", day_index)
            start_step.setdefault("state_events", {}).setdefault(template["channel"], []).append(
                {
                    "id": start_id,
                    "text": template["start_text"],
                    "value": None,
                    "meta": {"phase": "in_progress"},
                }
            )
            complete_step.setdefault("state_events", {}).setdefault(template["channel"], []).append(
                {
                    "id": trigger_id,
                    "text": template["complete_text"],
                    "value": None,
                    "meta": {"phase": "complete"},
                }
            )
            start_step["_hidden_lines"].append(template["start_narrative"])
            add_task(
                day_ctx["tasks"],
                {
                    "id": trigger_id,
                    "label": template["label"],
                    "type": "event",
                    "cue_id": trigger_id,
                    "cue_channel": template["channel"],
                    "regular": False,
                    "encoding": "start",
                },
            )
            day_ctx["_cue_index"][trigger_id] = {
                "step_id": complete_step["id"],
                "display": template["label"],
                "family": template["id_base"],
                "domain": template["domain"],
                "channel": template["channel"],
            }
            continue

        step = choose_step_for_dayparts(day_ctx["steps"], template["dayparts"], rng)
        if step is None:
            continue
        trigger_id = unique_task_id(template["id_base"], day_index)
        payload = {"meta": template.get("meta", {})}
        if "value" in template:
            payload["value"] = template["value"]
        add_state_event(
            day_ctx,
            step,
            template["channel"],
            trigger_id,
            template["text"],
            template["domain"],
            payload,
        )
        add_task(
            day_ctx["tasks"],
            {
                "id": trigger_id,
                "label": template["label"],
                "type": "event",
                "cue_id": trigger_id,
                "cue_channel": template["channel"],
                "regular": False,
                "encoding": "start",
            },
        )
        if rng.random() < 0.6:
            reminder_step = choose_intro_step(day_ctx["steps"], step["time"], rng)
            reminder_step["_notes"].append(ensure_period(build_state_hint_text(template)))

    lure_count = rng.randint(10, 12)
    day_ctx["lures"] = deepcopy(rng.sample(LURE_LIBRARY, k=lure_count))
    return day_ctx


def build_start_instructions(day_ctx, rng):
    header_pool = [
        "Today's loose plan:",
        "A few things are already on your mind:",
        "You start the day with a short mental list:",
        "Before the day gets crowded, these are the main things you need to keep track of:",
    ]
    visible_tasks = [
        task
        for task in day_ctx["tasks"]
        if not task.get("regular") and not task.get("cross_day")
    ]
    if not visible_tasks:
        return
    lines = [choice_with_fallback(rng, header_pool)]
    visible_tasks = sorted(visible_tasks, key=lambda task: task["label"].lower())
    for task in visible_tasks:
        lines.append(f"- {ensure_period(task['label'])}")
    day_ctx["start_instructions"] = lines


def build_state_hint_text(template):
    channel = template["channel"]
    if channel == "price_tracker":
        target = re.sub(r"^Buy the ", "", base_task_label(template["label"]), flags=re.IGNORECASE)
        return f"You keep in mind that the {target.lower()} price might drop later."
    if channel == "bank_balance":
        return "You keep in mind that your balance might dip later."
    if channel == "appointment_portal":
        return "You have a feeling the appointment portal may open a better slot later."
    if channel == "library_hold":
        return "You may get a library notice later today."
    if channel == "reservation_waitlist":
        return "You may hear back from the waitlist later."
    if channel == "calendar":
        return "You have a feeling the calendar may shift again before the day is over."
    if channel == "course_portal":
        return "You suspect the course portal could change again later."
    if channel == "email":
        return "You expect another email to land later."
    return f"You keep in mind that {channel.replace('_', ' ')} may matter later."


def make_sentence_unique(sentence, time_text, rendered_sentences):
    base = ensure_period(sentence)
    core = base.rstrip(".")
    candidates = [
        base,
        f"For a moment, {lower_first(core)}.",
        f"Before you move on, {lower_first(core)}.",
        f"{base.rstrip('.')} again.",
    ]
    for candidate in candidates:
        if candidate not in rendered_sentences:
            rendered_sentences.add(candidate)
            return candidate
    rendered_sentences.add(base)
    return base


def pick_scene_sentence(day_ctx, step, rng, used_template_sentences):
    phase = step["_phase"]
    focus_pool = []
    for domain in day_ctx.get("_domains", ()):
        focus_pool.extend(SCENE_FOCUS_BY_DOMAIN.get(domain, ()))
    focus_pool.extend(
        [
            "your keys",
            "your bag",
            "the note on your phone",
            "the loose receipt",
        ]
    )
    focus = rng.choice(focus_pool)
    pools = {
        "pre11": [
            f"You make sure {focus} is where you can reach it before heading out.",
            f"You move {focus} closer to the top of the pile and check the clock.",
            f"You set {focus} by the door so you do not forget it.",
            f"You glance at {focus}, clear a little space, and get moving again.",
            f"You shift {focus} into your bag and look over what has to happen first.",
            f"You pick up {focus}, put it back down, and sort out the start of the day.",
            f"You check that {focus} is still with you before the morning gets away from you.",
            f"You straighten the counter, check on {focus}, and head to the next thing.",
        ],
        "mid": [
            f"You set {focus} on the table for a minute and look over the rest of the afternoon.",
            f"You move {focus} into the front pocket of your bag so it is easier to grab later.",
            f"You sit down for a moment, check {focus}, and keep going.",
            f"You line up {focus} with the rest of your things and keep the day moving.",
            f"You look over {focus}, send one quick reply, and move on.",
            f"You put {focus} where you can see it and sort out the next two errands.",
            f"You check the time, tuck away {focus}, and head to the next thing.",
            f"You clear a little space, glance at {focus}, and keep the afternoon together.",
        ],
        "eve": [
            f"You set {focus} near the door and look at what is still left tonight.",
            f"You rinse a dish, check on {focus}, and keep moving.",
            f"You put {focus} where you will see it again and keep the evening going.",
            f"You clear a little space on the counter, move {focus} aside, and look at what remains.",
            f"You slow down for a minute, check {focus}, and sort out the rest of the night.",
            f"You put one thing away, glance at {focus}, and keep going.",
            f"You pause with a glass of water, look at {focus}, and see what is still unresolved.",
            f"You set your bag down, check {focus}, and keep the evening in order.",
        ],
        "late": [
            f"You plug in your phone, set {focus} aside, and call it a night.",
            f"You brush your teeth, check that {focus} is still where you need it, and head to bed.",
            f"You turn down the lights, leave {focus} out for tomorrow, and settle in for the night.",
            f"You set out tomorrow's things, move {focus} into place, and head toward bed.",
            f"You wash up, leave {focus} where you will see it in the morning, and get ready to sleep.",
            f"You check the lock, set {focus} down, and let the day end.",
            f"You put the last cup in the sink, move {focus} aside, and get ready for bed.",
            f"You dim the room, plug in your phone, and leave {focus} for tomorrow.",
        ],
    }
    return choice_with_fallback(rng, pools[phase], used_template_sentences)


def render_step_texts(day_ctx, rng, used_template_sentences, rendered_sentences):
    breakfast_variants = [
        "You make breakfast while trying to remember what needs to happen first.",
        "Breakfast is the one brief part of the morning that still feels under your control.",
        "You put breakfast together while mentally sorting out the day.",
        "You start with breakfast and a quick scan of what the day might turn into.",
        "Breakfast is less about food than about getting your bearings.",
        "Breakfast lands right before the rest of the day starts competing for space.",
        "Breakfast gives you one last orderly moment before the day gets busier.",
        "Breakfast comes together while you're already thinking two steps ahead.",
    ]
    dinner_variants = [
        "You pause long enough to put dinner together.",
        "Dinner happens right in the middle of the evening's cleanup and catch-up.",
        "You make dinner while trying not to lose track of the rest of the evening.",
        "You pull dinner together before the rest of the night gets thinner and quieter.",
        "Dinner is one more moving part in the evening rather than a full break from it.",
        "Dinner arrives after the day has already started spilling into the night.",
        "Dinner is mostly a marker that the day has tilted into evening.",
        "Dinner feels more like a pause button than a real stop.",
    ]
    for step in day_ctx["steps"]:
        parts = []
        if "breakfast" in step["cues"]:
            base_sentence = choice_with_fallback(
                rng,
                breakfast_variants,
                used_template_sentences,
            )
            parts.append(make_sentence_unique(base_sentence, step["time"], rendered_sentences))
        elif "dinner" in step["cues"]:
            base_sentence = choice_with_fallback(
                rng,
                dinner_variants,
                used_template_sentences,
            )
            parts.append(make_sentence_unique(base_sentence, step["time"], rendered_sentences))
        else:
            if not step["_visible_cues"] and not step["_notes"] and not step["_hidden_lines"] and not step["updates"]:
                parts.append(
                    make_sentence_unique(
                        pick_scene_sentence(day_ctx, step, rng, used_template_sentences),
                        step["time"],
                        rendered_sentences,
                    )
                )

        for cue_sentence in step["_visible_cues"]:
            if cue_sentence:
                parts.append(make_sentence_unique(cue_sentence, step["time"], rendered_sentences))
        for hidden_line in step["_hidden_lines"]:
            parts.append(make_sentence_unique(hidden_line, step["time"], rendered_sentences))
        for note in step["_notes"]:
            parts.append(make_sentence_unique(note, step["time"], rendered_sentences))
        for update in step["updates"]:
            parts.append(make_sentence_unique(update["_message"], step["time"], rendered_sentences))
        step["text"] = join_sentences(parts)
        if "log about the" in step["text"] or "updated the " in step["text"]:
            raise RuntimeError(f"Detected banned phrase in step text: {step['text']}")


def add_updates(day_contexts, rng):
    reschedule_candidates = []
    cancel_candidates = []
    override_candidates = []
    for day_ctx in day_contexts:
        steps = day_ctx["steps"]
        for task in day_ctx["tasks"]:
            if task.get("regular") or task.get("cross_day"):
                continue
            if task["type"] == "time":
                reschedule_candidates.append((day_ctx, task))
                cancel_candidates.append((day_ctx, task))
            elif task["type"] == "event" and task.get("cue_channel", "narrative") == "narrative":
                cancel_candidates.append((day_ctx, task))
                override_candidates.append((day_ctx, task))

    rng.shuffle(reschedule_candidates)
    rng.shuffle(cancel_candidates)
    rng.shuffle(override_candidates)
    used_tasks = set()
    update_count_by_day = Counter()

    def can_add(day_ctx):
        return update_count_by_day[day_ctx["name"]] < 2

    for day_ctx, task in reschedule_candidates[:]:
        if len(used_tasks) >= 6:
            break
        if task["id"] in used_tasks or not can_add(day_ctx):
            continue
        source_step = choose_update_source_step(day_ctx["steps"], task["target_time"], rng)
        if source_step is None:
            continue
        step_candidates = [
            step for step in day_ctx["steps"]
            if step["time"] != task["target_time"]
            and time_to_minutes_local(step["time"]) > time_to_minutes_local(source_step["time"])
        ]
        task_domain = task.get("_domain")
        if task_domain in {"work", "admin", "class"}:
            preferred_candidates = [
                step for step in step_candidates
                if time_to_minutes_local(step["time"]) <= time_to_minutes_local("17:40")
            ]
            if preferred_candidates:
                step_candidates = preferred_candidates
        elif task_domain == "health":
            preferred_candidates = [
                step for step in step_candidates
                if time_to_minutes_local(step["time"]) <= time_to_minutes_local("18:00")
            ]
            if preferred_candidates:
                step_candidates = preferred_candidates
        if not step_candidates:
            continue
        update_cue = unique_task_id(f"reschedule_notice_{task['id']}", 0)
        source_step["cues"].append(update_cue)
        new_time = rng.choice(step_candidates)["time"]
        new_label = replace_terminal_time(task["label"], new_time)
        message = choice_with_fallback(
            rng,
            [
                f"A quick update comes in: {lower_first(base_task_label(task['label']))} should happen at {new_time} instead of {task['target_time']}.",
                f"You get a timing change for {lower_first(base_task_label(task['label']))}: it now fits better at {new_time}.",
                f"A reschedule note lands for {lower_first(base_task_label(task['label']))}: move it to {new_time}.",
                f"The timing shifts a little: {lower_first(base_task_label(task['label']))} moves to {new_time}.",
                f"A later note nudges {lower_first(base_task_label(task['label']))} to {new_time}.",
                f"You get a small scheduling change: {lower_first(base_task_label(task['label']))} is better at {new_time}.",
                f"The latest update puts {lower_first(base_task_label(task['label']))} at {new_time}.",
            ],
        )
        source_step["updates"].append(
            {
                "task_id": task["id"],
                "action": "reschedule",
                "new_target_time": new_time,
                "new_label": new_label,
                "new_action_text": derive_action_text_from_label(new_label),
                "cue_id": update_cue,
                "_message": message,
            }
        )
        source_step["_visible_cues"].append(choice_with_fallback(
            rng,
            [
                f"A reschedule note about {lower_first(base_task_label(task['label']))} flashes across the top of your screen.",
                f"A quick timing message about {lower_first(base_task_label(task['label']))} comes in while you're moving.",
                f"An updated time for {lower_first(base_task_label(task['label']))} comes through.",
                f"A quick scheduling note about {lower_first(base_task_label(task['label']))} comes in.",
                f"You get a brief note that the timing for {lower_first(base_task_label(task['label']))} has shifted.",
                f"A short follow-up changes the timing for {lower_first(base_task_label(task['label']))}.",
                f"The timing for {lower_first(base_task_label(task['label']))} shifts a bit on your phone.",
            ],
        ))
        used_tasks.add(task["id"])
        update_count_by_day[day_ctx["name"]] += 1

    for day_ctx, task in cancel_candidates:
        if len(used_tasks) >= 8:
            break
        if task["id"] in used_tasks or not can_add(day_ctx):
            continue
        target_time = task.get("target_time")
        due_time = target_time
        if task["type"] == "event":
            cue_info = day_ctx["_cue_index"].get(task["cue_id"])
            if not cue_info:
                continue
            due_time = next(step["time"] for step in day_ctx["steps"] if step["id"] == cue_info["step_id"])
        source_step = choose_update_source_step(day_ctx["steps"], due_time, rng)
        if source_step is None:
            continue
        update_cue = unique_task_id(f"cancel_notice_{task['id']}", 0)
        source_step["cues"].append(update_cue)
        gerund = action_gerund_from_label(task["label"])
        message = choice_with_fallback(
            rng,
            [
                f"A cancellation note comes through: you can skip {gerund} today.",
                f"You get word that {gerund} no longer needs to happen today.",
                f"A quick message clears it: you do not need to worry about {gerund} today.",
                f"It turns out {gerund} can wait and does not need to happen today.",
                f"A follow-up comes in saying you do not need to handle {gerund} today.",
            ],
        )
        source_step["updates"].append(
            {
                "task_id": task["id"],
                "action": "cancel",
                "cue_id": update_cue,
                "_message": message,
            }
        )
        source_step["_visible_cues"].append(choice_with_fallback(
            rng,
            [
                f"A short cancellation note about {gerund} shows up on your phone.",
                f"A message lands and knocks {gerund} off your list.",
                f"A quick follow-up arrives and cancels {gerund}.",
                f"A brief update comes in saying you can skip {gerund}.",
                f"You get a note that {gerund} does not need to happen after all.",
            ],
        ))
        used_tasks.add(task["id"])
        update_count_by_day[day_ctx["name"]] += 1

    for day_ctx, task in override_candidates:
        if len(used_tasks) >= 11:
            break
        if task["id"] in used_tasks or not can_add(day_ctx):
            continue
        original_info = day_ctx["_cue_index"].get(task["cue_id"])
        if not original_info:
            continue
        original_time = next(step["time"] for step in day_ctx["steps"] if step["id"] == original_info["step_id"])
        later_steps = [step for step in day_ctx["steps"] if time_to_minutes_local(step["time"]) > time_to_minutes_local(original_time)]
        if not later_steps:
            continue
        source_step = choose_update_source_step(day_ctx["steps"], original_time, rng)
        if source_step is None:
            continue
        target_step = rng.choice(later_steps)
        display, cue_sentence = rng.choice(OVERRIDE_DISPLAY_LIBRARY)
        new_cue_id = unique_task_id(f"override_{task['id']}", 0)
        source_update_cue = unique_task_id(f"override_notice_{task['id']}", 0)
        target_step["cues"].append(new_cue_id)
        target_step["_visible_cues"].append(cue_sentence)
        day_ctx["_cue_index"][new_cue_id] = {
            "step_id": target_step["id"],
            "display": display,
            "family": normalize_family_id(task["cue_id"]),
            "domain": original_info.get("domain"),
            "channel": "narrative",
        }
        source_step["cues"].append(source_update_cue)
        source_step["_visible_cues"].append(choice_with_fallback(
            rng,
            [
                f"You get a follow-up with corrected instructions for {lower_first(base_task_label(task['label']))}.",
                f"A quick correction comes in before you get to {lower_first(base_task_label(task['label']))}.",
                f"A later message changes what you should watch for before you {lower_first(base_task_label(task['label']))}.",
            ],
        ))
        new_label = override_label(task["label"], display)
        message = choice_with_fallback(
            rng,
            [
                f"You should wait for {display} before you {lower_first(base_task_label(task['label']))}.",
                f"The new instruction is to use {display} as the cue for {lower_first(base_task_label(task['label']))}.",
                f"Instead of the earlier cue, watch for {display} before you {lower_first(base_task_label(task['label']))}.",
            ],
        )
        source_step["updates"].append(
            {
                "task_id": task["id"],
                "action": "override",
                "new_cue_id": new_cue_id,
                "new_label": new_label,
                "new_action_text": derive_action_text_from_label(new_label),
                "cue_id": source_update_cue,
                "_message": message,
            }
        )
        used_tasks.add(task["id"])
        update_count_by_day[day_ctx["name"]] += 1


def add_cross_day_tasks(day_contexts, rng):
    cue_targets = []
    for target_index, day_ctx in enumerate(day_contexts):
        for cue_id, info in day_ctx["_cue_index"].items():
            if info["channel"] != "narrative":
                continue
            if cue_id in {"breakfast", "dinner"}:
                continue
            if cue_id.startswith("override_") or cue_id.startswith("cancel_notice_") or cue_id.startswith("reschedule_notice_"):
                continue
            cue_targets.append((target_index, day_ctx, cue_id, info))
    rng.shuffle(cue_targets)
    additions = 0
    target_cues = set()
    source_counts = Counter()
    used_actions = set()
    for target_index, target_day, cue_id, info in cue_targets:
        if additions >= 7:
            break
        if cue_id in target_cues:
            continue
        if info.get("family") in CROSS_DAY_BLOCKED_FAMILIES:
            continue
        source_candidates = [index for index in range(max(0, target_index - 3), target_index)]
        if not source_candidates:
            continue
        source_index = rng.choice(source_candidates)
        source_day = day_contexts[source_index]
        if source_counts[source_day["name"]] >= 2:
            continue
        action_pool = CROSS_DAY_ACTIONS_BY_FAMILY.get(
            info.get("family"),
            CROSS_DAY_ACTIONS.get(info.get("domain"), CROSS_DAY_ACTIONS["errands"]),
        )
        available_actions = [action for action in action_pool if (info.get("domain"), action) not in used_actions]
        if not available_actions:
            available_actions = action_pool
        action = rng.choice(available_actions)
        crossday_label = f"{sentence_case(action)} when you notice {info['display']}"
        target_day["tasks"].append(
            {
                "id": f"crossday_{additions + 1}",
                "label": crossday_label,
                "action_text": ensure_period(sentence_case(action)),
                "type": "event",
                "cue_id": cue_id,
                "regular": False,
                "encoding": "start",
                "cross_day": True,
                "cross_day_offset": target_index - source_index,
            }
        )
        note_sentence = f"On {target_day['name']}, {ensure_period(crossday_label)}"
        source_step = choose_light_step(
            source_day["steps"][: max(2, min(4, len(source_day["steps"])))],
            rng,
        )
        source_step["_notes"].append(
            choice_with_fallback(
                rng,
                [
                    f"You leave yourself a note: {note_sentence}",
                    f"You jot down a quick reminder: {note_sentence}",
                    f"You make a note for later: {note_sentence}",
                    f"You add a reminder to yourself: {note_sentence}",
                ],
            )
        )
        target_cues.add(cue_id)
        source_counts[source_day["name"]] += 1
        used_actions.add((info.get("domain"), action))
        additions += 1


def strip_internal(day_ctx):
    cleaned_steps = []
    for step in day_ctx["steps"]:
        payload = {
            "id": step["id"],
            "time": step["time"],
            "text": step["text"],
            "options": step["options"],
            "cues": step["cues"],
            "updates": [
                {k: v for k, v in update.items() if not k.startswith("_")}
                for update in step["updates"]
            ],
        }
        if step.get("state_events"):
            payload["state_events"] = step["state_events"]
        cleaned_steps.append(payload)
    tasks = []
    for task in day_ctx["tasks"]:
        payload = {k: v for k, v in task.items() if not k.startswith("_")}
        tasks.append(payload)
    disambiguate_day_action_texts(tasks)
    return {
        "name": day_ctx["name"],
        "start_instructions": day_ctx["start_instructions"],
        "tasks": tasks,
        "lures": day_ctx["lures"],
        "steps": cleaned_steps,
    }


def build_week(seed, scenario_name):
    rng = random.Random(seed)
    threads = rng.sample(THREAD_LIBRARY, k=4)
    thread_domains = tuple(sorted({domain for thread in threads for domain in thread["domains"]}))
    archetypes = rng.sample(ARCHETYPES, k=7)
    used_time_signatures = set()
    used_event_ids = set()
    used_time_task_ids = set()
    day_contexts = []
    for day_index, (day_name, archetype) in enumerate(zip(DAY_NAMES, archetypes), start=1):
        day_ctx = build_day_context(
            day_index,
            day_name,
            archetype,
            thread_domains,
            rng,
            used_time_signatures,
            used_event_ids,
            used_time_task_ids,
        )
        day_contexts.append(day_ctx)

    add_updates(day_contexts, rng)
    add_cross_day_tasks(day_contexts, rng)
    for day_ctx in day_contexts:
        build_start_instructions(day_ctx, rng)

    used_template_sentences = set()
    rendered_sentences = set()
    for day_ctx in day_contexts:
        render_step_texts(day_ctx, rng, used_template_sentences, rendered_sentences)

    week = {
        "scenario_name": scenario_name,
        "time_visible_by_default": False,
        "state_visibility": {channel: False for channel in STATE_CHANNEL_CONFIG},
        "state_channels": deepcopy(STATE_CHANNEL_CONFIG),
        "days": [strip_internal(day_ctx) for day_ctx in day_contexts],
    }
    stats = compute_v9_stats(week, archetype_names=[day_ctx["archetype"] for day_ctx in day_contexts])
    return week, stats


def compute_v9_stats(week, archetype_names=None):
    repeated_sentences = Counter()
    cue_families = Counter()
    time_signatures = []
    update_mix = Counter()
    cross_day_total = 0
    for day in week["days"]:
        time_signatures.append(tuple(step["time"] for step in day["steps"]))
        for task in day["tasks"]:
            if task.get("regular"):
                continue
            if task.get("cross_day"):
                cross_day_total += 1
            cue_id = task.get("cue_id")
            if cue_id and cue_id not in {"breakfast", "dinner"}:
                cue_families[normalize_family_id(cue_id)] += 1
        for step in day["steps"]:
            for sentence in split_sentences(step["text"]):
                if "Take asthma medication" in sentence or "Take antibiotic" in sentence:
                    continue
                repeated_sentences[sentence] += 1
            for update in step.get("updates", []):
                update_mix[update["action"]] += 1
    stats = {
        "steps_per_day": [len(day["steps"]) for day in week["days"]],
        "time_signatures": time_signatures,
        "cross_day_total": cross_day_total,
        "update_total": sum(update_mix.values()),
        "update_mix": dict(update_mix),
        "repeated_sentences": {k: v for k, v in repeated_sentences.items() if v > 1},
        "cue_family_counts": dict(cue_families),
    }
    if archetype_names is not None:
        stats["archetypes"] = list(archetype_names)
    return stats


def validate_v9_stats(week, stats):
    errors = []
    if len(week.get("days", [])) != 7:
        errors.append("v9 week must contain exactly 7 days")
    step_counts = stats["steps_per_day"]
    if any(count < 9 or count > 14 for count in step_counts):
        errors.append(f"step counts out of range: {step_counts}")
    signatures = stats["time_signatures"]
    if len(set(signatures)) != len(signatures):
        errors.append("daily time signatures must be unique")
    repeated = stats["repeated_sentences"]
    if repeated:
        errors.append(f"repeated non-routine sentences found: {sorted(repeated)[:5]}")
    archetypes = stats.get("archetypes", [])
    if archetypes and len(set(archetypes)) != len(archetypes):
        errors.append(f"archetypes repeated within the week: {archetypes}")
    cross_day_total = stats["cross_day_total"]
    if not 6 <= cross_day_total <= 8:
        errors.append(f"cross_day_total out of range: {cross_day_total}")
    update_total = stats["update_total"]
    if not 10 <= update_total <= 14:
        errors.append(f"update_total out of range: {update_total}")
    update_mix = stats["update_mix"]
    reschedules = update_mix.get("reschedule", 0)
    if reschedules < max(update_mix.get("cancel", 0), update_mix.get("override", 0)):
        errors.append(f"reschedules must be the dominant update type: {update_mix}")
    for family, count in stats["cue_family_counts"].items():
        if count > 2:
            errors.append(f"cue family reused too often: {family} x{count}")
    for day in week["days"]:
        for step in day["steps"]:
            if "log about the" in step["text"] or "updated the " in step["text"]:
                errors.append(f"banned phrasing in {day['name']} {step['id']}")
            if step.get("time") and step["time"] in step.get("text", ""):
                errors.append(
                    f"step text leaks current step time in {day['name']} {step['id']}"
                )
            for item in step.get("state_events", {}).get("shipment_status", []):
                if item.get("meta", {}).get("phase") == "complete":
                    if time_to_minutes_local(step["time"]) > time_to_minutes_local("18:00"):
                        errors.append(
                            f"shipment completion is too late in {day['name']} {step['id']} at {step['time']}"
                        )
    return errors


def summarize_v9_stats(stats):
    lines = [
        "v9 stats:",
        f"- steps/day: {stats['steps_per_day']}",
        f"- cross-day total: {stats['cross_day_total']}",
        f"- update total: {stats['update_total']}",
        f"- update mix: {stats['update_mix']}",
        f"- repeated sentence count: {len(stats['repeated_sentences'])}",
        f"- top cue family reuse: {dict(sorted(stats['cue_family_counts'].items(), key=lambda item: (-item[1], item[0]))[:8])}",
    ]
    if "archetypes" in stats:
        lines.append(f"- archetypes: {stats['archetypes']}")
    return "\n".join(lines)


def generate_week_v9(seed=42, scenario_name="synthetic_week_v9", max_attempts=200):
    for attempt in range(max_attempts):
        attempt_seed = f"pm-bench-v9:{seed}:{attempt}"
        week, stats = build_week(attempt_seed, scenario_name)
        scenario_errors, scenario_warnings = validate_scenario(week)
        groundtruth_report = compute_scenario_groundtruth(week)
        if scenario_warnings:
            # Warnings are useful for debugging but should not reject the week.
            pass
        v9_errors = validate_v9_stats(week, stats)
        if not groundtruth_report["solvable"]:
            v9_errors = v9_errors + groundtruth_report["issues"]
        if not scenario_errors and not v9_errors:
            return week, stats
    raise RuntimeError(
        "Unable to generate a valid v9 week after "
        f"{max_attempts} attempts; last errors: {scenario_errors + v9_errors}"
    )
