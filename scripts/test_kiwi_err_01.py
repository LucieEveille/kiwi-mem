#!/usr/bin/env python3
"""ERR-01 v1.2: production ASGI/functions, fake storage and model, loopback TCP.

No lifespan, .env, real database, or real model calls. Stage A changes only this
new guard. --evidence writes per-case observations including actual return hits.
The AST detector self-test seam is intentionally absent in stage A per contract;
stage B supplies the test-local find_raw_exception_returns helper (not app code).
"""
from __future__ import annotations
import argparse
import ast
import asyncio
from contextlib import ExitStack, contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['DATABASE_URL']='postgresql://unused:unused@127.0.0.1:1/unused'
import httpx
import httpcore
import main as app
import database as db
import config
import security
import daily_digest as daily
import dream

REAL_CLIENT=httpx.AsyncClient
SENTINEL='ERR01_CANARY_c29fa701'
BASE='231b3ebd32e7e1775d4969e60f12c2e694528356'
EXITS=[{'id': 'E1',
  'function': 'extract_file_content',
  'line': 1821,
  'route': 'POST /v1/files/extract',
  'catch': 'Exception'},
 {'id': 'X1',
  'function': 'chat_completions',
  'line': 2033,
  'route': 'POST /v1/chat/completions',
  'catch': 'ValueError'},
 {'id': 'D1',
  'function': 'debug_memories',
  'line': 3852,
  'route': 'GET /debug/memories',
  'catch': 'Exception'},
 {'id': 'D2',
  'function': 'delete_single_memory',
  'line': 3873,
  'route': 'DELETE /debug/memories/{memory_id}',
  'catch': 'Exception'},
 {'id': 'D3',
  'function': 'batch_delete_memories',
  'line': 3894,
  'route': 'POST /debug/memories/batch-delete',
  'catch': 'Exception'},
 {'id': 'D4',
  'function': 'batch_update_memories',
  'line': 3942,
  'route': 'POST /debug/memories/batch-update',
  'catch': 'Exception'},
 {'id': 'D5',
  'function': 'clear_memories',
  'line': 3969,
  'route': 'DELETE /debug/memories',
  'catch': 'Exception'},
 {'id': 'D6',
  'function': 'debug_memory_heat',
  'line': 4004,
  'route': 'GET /debug/memory-heat',
  'catch': 'Exception'},
 {'id': 'D7',
  'function': 'toggle_memory_permanent',
  'line': 4084,
  'route': 'POST /debug/memories/{memory_id}/toggle-permanent',
  'catch': 'Exception'},
 {'id': 'D8',
  'function': 'api_save_compression_summary',
  'line': 4432,
  'route': 'POST /admin/compression-summary',
  'catch': 'Exception'},
 {'id': 'D9',
  'function': 'api_get_compression_summaries',
  'line': 4456,
  'route': 'GET /admin/compression-summaries',
  'catch': 'Exception'},
 {'id': 'D10',
  'function': 'api_get_calendar_day',
  'line': 4475,
  'route': 'GET /calendar/{date}',
  'catch': 'Exception'},
 {'id': 'D11',
  'function': 'api_get_calendar_range',
  'line': 4502,
  'route': 'GET /calendar',
  'catch': 'Exception'},
 {'id': 'D12',
  'function': 'api_calendar_period_audit',
  'line': 4513,
  'route': 'GET /admin/calendar-period-audit',
  'catch': 'Exception'},
 {'id': 'D13',
  'function': 'api_save_calendar_page',
  'line': 4537,
  'route': 'PUT /admin/calendar/{date}',
  'catch': 'ValueError'},
 {'id': 'D14',
  'function': 'api_save_calendar_page',
  'line': 4539,
  'route': 'PUT /admin/calendar/{date}',
  'catch': 'Exception'},
 {'id': 'D15',
  'function': 'api_delete_calendar_page',
  'line': 4550,
  'route': 'DELETE /admin/calendar/{date}',
  'catch': 'Exception'},
 {'id': 'D16',
  'function': 'api_create_comment',
  'line': 4574,
  'route': 'POST /comments',
  'catch': 'Exception'},
 {'id': 'D17', 'function': 'api_get_comments', 'line': 4588, 'route': 'GET /comments', 'catch': 'Exception'},
 {'id': 'D18',
  'function': 'api_delete_comment',
  'line': 4599,
  'route': 'DELETE /comments/{comment_id}',
  'catch': 'Exception'},
 {'id': 'D19',
  'function': 'api_get_scenes',
  'line': 4735,
  'route': 'GET /dream/scenes',
  'catch': 'Exception'},
 {'id': 'D20',
  'function': 'api_delete_dream',
  'line': 4768,
  'route': 'DELETE /admin/dream/{dream_id}',
  'catch': 'Exception'},
 {'id': 'D21',
  'function': 'api_get_default_prompts',
  'line': 4960,
  'route': 'GET /admin/default-prompts',
  'catch': 'Exception'},
 {'id': 'D22',
  'function': 'api_restore_prompt',
  'line': 4978,
  'route': 'POST /admin/restore-prompt/{key}',
  'catch': 'Exception'},
 {'id': 'D23',
  'function': 'api_get_categories',
  'line': 5334,
  'route': 'GET /admin/categories',
  'catch': 'Exception'},
 {'id': 'D24',
  'function': 'api_create_category',
  'line': 5355,
  'route': 'POST /admin/categories',
  'catch': 'Exception'},
 {'id': 'D25',
  'function': 'api_update_category',
  'line': 5368,
  'route': 'PUT /admin/categories/{category_id}',
  'catch': 'Exception'},
 {'id': 'D26',
  'function': 'api_delete_category',
  'line': 5380,
  'route': 'DELETE /admin/categories/{category_id}',
  'catch': 'Exception'},
 {'id': 'D27',
  'function': 'api_mcp_list_tools',
  'line': 5472,
  'route': 'POST /admin/mcp/list-tools',
  'catch': 'Exception'},
 {'id': 'D28',
  'function': 'api_get_system_prompt',
  'line': 5653,
  'route': 'GET /admin/system-prompt',
  'catch': 'Exception'},
 {'id': 'D29',
  'function': 'api_set_system_prompt',
  'line': 5665,
  'route': 'PUT /admin/system-prompt',
  'catch': 'Exception'},
 {'id': 'D30',
  'function': 'api_search_messages',
  'line': 5702,
  'route': 'GET /search/messages',
  'catch': 'Exception'},
 {'id': 'D31',
  'function': 'api_sync_get_conversations',
  'line': 5770,
  'route': 'GET /sync/conversations',
  'catch': 'Exception'},
 {'id': 'D32',
  'function': 'api_sync_get_conversation',
  'line': 5783,
  'route': 'GET /sync/conversations/{conv_id}',
  'catch': 'Exception'},
 {'id': 'D33',
  'function': 'api_sync_create_conversation',
  'line': 5808,
  'route': 'POST /sync/conversations',
  'catch': 'Exception'},
 {'id': 'D34',
  'function': 'api_sync_upsert_conversation',
  'line': 5838,
  'route': 'PUT /sync/conversations/{conv_id}',
  'catch': 'Exception'},
 {'id': 'D35',
  'function': 'api_sync_patch_conversation',
  'line': 5856,
  'route': 'PATCH /sync/conversations/{conv_id}',
  'catch': 'Exception'},
 {'id': 'D36',
  'function': 'api_sync_upsert_message',
  'line': 5890,
  'route': 'PUT /sync/conversations/{conv_id}/messages/{msg_id}',
  'catch': 'Exception'},
 {'id': 'D37',
  'function': 'api_sync_get_projects',
  'line': 5922,
  'route': 'GET /sync/projects',
  'catch': 'Exception'},
 {'id': 'D38',
  'function': 'api_sync_create_project',
  'line': 5938,
  'route': 'POST /sync/projects',
  'catch': 'Exception'},
 {'id': 'D39',
  'function': 'api_sync_upsert_project',
  'line': 5953,
  'route': 'PUT /sync/projects/{proj_id}',
  'catch': 'Exception'},
 {'id': 'D40',
  'function': 'api_sync_patch_project',
  'line': 5970,
  'route': 'PATCH /sync/projects/{proj_id}',
  'catch': 'Exception'},
 {'id': 'D41',
  'function': 'api_sync_delete_project',
  'line': 5986,
  'route': 'DELETE /sync/projects/{proj_id}',
  'catch': 'Exception'},
 {'id': 'D42',
  'function': 'api_delete_file_chunks',
  'line': 6024,
  'route': 'DELETE /projects/{proj_id}/files/{file_id}/chunks',
  'catch': 'Exception'},
 {'id': 'D43',
  'function': 'api_sync_put_settings',
  'line': 6094,
  'route': 'PUT /sync/settings',
  'catch': 'Exception'},
 {'id': 'D44',
  'function': 'api_get_reminders',
  'line': 6301,
  'route': 'GET /reminders',
  'catch': 'Exception'},
 {'id': 'D45',
  'function': 'api_create_reminder',
  'line': 6311,
  'route': 'POST /reminders',
  'catch': 'Exception'},
 {'id': 'D46',
  'function': 'api_get_due_reminders',
  'line': 6323,
  'route': 'GET /reminders/due',
  'catch': 'Exception'},
 {'id': 'D47',
  'function': 'api_fire_reminder',
  'line': 6336,
  'route': 'POST /reminders/{rid}/fire',
  'catch': 'Exception'},
 {'id': 'D48',
  'function': 'api_update_reminder',
  'line': 6348,
  'route': 'PUT /reminders/{rid}',
  'catch': 'Exception'},
 {'id': 'D49',
  'function': 'api_delete_reminder',
  'line': 6359,
  'route': 'DELETE /reminders/{rid}',
  'catch': 'Exception'}]
PARSES=[{'line': 2029,
  'function': 'chat_completions',
  'routes': ['POST /v1/chat/completions'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 3882,
  'function': 'batch_delete_memories',
  'routes': ['POST /debug/memories/batch-delete'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 3903,
  'function': 'batch_update_memories',
  'routes': ['POST /debug/memories/batch-update'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 3953,
  'function': 'clear_memories',
  'routes': ['DELETE /debug/memories'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4018,
  'function': 'update_single_memory',
  'routes': ['PUT /debug/memories/{memory_id}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4044,
  'function': 'add_memory_manual',
  'routes': ['POST /debug/memories'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4113,
  'function': 'api_embedding_rebuild',
  'routes': ['POST /admin/embedding-rebuild'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4166,
  'function': 'api_extract_now',
  'routes': ['POST /admin/extract-now'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4413,
  'function': 'api_save_compression_summary',
  'routes': ['POST /admin/compression-summary'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4522,
  'function': 'api_save_calendar_page',
  'routes': ['PUT /admin/calendar/{date}'],
  'call': 'req.json',
  'source': 'req.json()'},
 {'line': 4562,
  'function': 'api_create_comment',
  'routes': ['POST /comments'],
  'call': 'req.json',
  'source': 'req.json()'},
 {'line': 4617,
  'function': 'api_dream_start',
  'routes': ['POST /dream/start'],
  'call': 'req.json',
  'source': 'req.json()'},
 {'line': 4643,
  'function': 'api_dream_start_detached',
  'routes': ['POST /dream/start-detached'],
  'call': 'req.json',
  'source': 'req.json()'},
 {'line': 4776,
  'function': 'api_update_scene',
  'routes': ['PUT /admin/scene/{scene_id}'],
  'call': 'req.json',
  'source': 'req.json()'},
 {'line': 4812,
  'function': 'api_set_config',
  'routes': ['PUT /admin/config/{key}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 4998,
  'function': 'api_create_provider',
  'routes': ['POST /admin/providers'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5024,
  'function': 'api_update_provider',
  'routes': ['PUT /admin/providers/{provider_id}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5273,
  'function': 'api_add_saved_model',
  'routes': ['POST /admin/providers/{provider_id}/saved-models'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5300,
  'function': 'api_update_saved_model',
  'routes': ['PUT /admin/saved-models/{model_pk_id}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5341,
  'function': 'api_create_category',
  'routes': ['POST /admin/categories'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5362,
  'function': 'api_update_category',
  'routes': ['PUT /admin/categories/{category_id}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5407,
  'function': 'api_set_search_config',
  'routes': ['PUT /admin/search-config'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5430,
  'function': 'api_search_test',
  'routes': ['POST /admin/search-test'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5460,
  'function': 'api_mcp_list_tools',
  'routes': ['POST /admin/mcp/list-tools'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5479,
  'function': 'api_mcp_clear_cache',
  'routes': ['POST /admin/mcp/clear-cache'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5660,
  'function': 'api_set_system_prompt',
  'routes': ['PUT /admin/system-prompt'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5736,
  'function': '_read_json_object',
  'routes': [],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5818,
  'function': 'api_sync_upsert_conversation',
  'routes': ['PUT /sync/conversations/{conv_id}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5948,
  'function': 'api_sync_upsert_project',
  'routes': ['PUT /sync/projects/{proj_id}'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 5999,
  'function': 'api_process_file_chunks',
  'routes': ['POST /projects/{proj_id}/files/{file_id}/process'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 6079,
  'function': 'api_sync_put_settings',
  'routes': ['PUT /sync/settings'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 6199,
  'function': 'api_sync_import_backup',
  'routes': ['POST /sync/import-backup'],
  'call': 'json.loads',
  'source': 'json.loads(zf.read("backup_meta.json"))'},
 {'line': 6205,
  'function': 'api_sync_import_backup',
  'routes': ['POST /sync/import-backup'],
  'call': 'json.loads',
  'source': 'json.loads(zf.read("projects.json"))'},
 {'line': 6214,
  'function': 'api_sync_import_backup',
  'routes': ['POST /sync/import-backup'],
  'call': 'json.loads',
  'source': 'json.loads(zf.read("conversations.json"))'},
 {'line': 6231,
  'function': 'api_sync_import_backup',
  'routes': ['POST /sync/import-backup'],
  'call': 'json.loads',
  'source': 'json.loads(zf.read("memories.json"))'},
 {'line': 6247,
  'function': 'api_sync_import_backup',
  'routes': ['POST /sync/import-backup'],
  'call': 'json.loads',
  'source': 'json.loads(zf.read("settings.json"))'},
 {'line': 6255,
  'function': 'api_sync_import_backup',
  'routes': ['POST /sync/import-backup'],
  'call': 'json.loads',
  'source': 'json.loads(zf.read("config.json"))'},
 {'line': 6277,
  'function': 'api_sync_reset',
  'routes': ['DELETE /sync/reset'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 6307,
  'function': 'api_create_reminder',
  'routes': ['POST /reminders'],
  'call': 'request.json',
  'source': 'request.json()'},
 {'line': 6342,
  'function': 'api_update_reminder',
  'routes': ['PUT /reminders/{rid}'],
  'call': 'request.json',
  'source': 'request.json()'}]
LOG_ROWS=[{'line': 208,
  'function': '_run_daily_digest_impl',
  'path': [('body', 19), ('body', 3), ('body', 4)],
  'kind': 'length'},
 {'line': 239,
  'function': '_run_daily_digest_impl',
  'path': [('body', 19), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 451,
  'function': 'update_user_profile',
  'path': [('body', 16), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 506,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 10), ('body', 1)],
  'kind': 'summary'},
 {'line': 508,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 10), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 513,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 11), ('body', 1)],
  'kind': 'summary'},
 {'line': 515,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 11), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 521,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 12), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 526,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 13), ('body', 1)],
  'kind': 'summary'},
 {'line': 528,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 13), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 532,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 14), ('body', 1)],
  'kind': 'summary'},
 {'line': 534,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 14), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 538,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 15), ('body', 1)],
  'kind': 'summary'},
 {'line': 540,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 15), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 545,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 16), ('body', 1)],
  'kind': 'summary'},
 {'line': 547,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('body', 16), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 553,
  'function': 'daily_digest_scheduler',
  'path': [('body', 2), ('body', 0), ('handlers', 1), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 600,
  'function': 'backfill_scene_embeddings',
  'path': [('body', 2), ('body', 6), ('body', 4), ('handlers', 0), ('body', 1)],
  'kind': 'safe_log'},
 {'line': 609,
  'function': 'backfill_scene_embeddings',
  'path': [('body', 2), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 655,
  'function': 'retire_stale_locks',
  'path': [('body', 1), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 783,
  'function': 'auto_soften_aging_memories',
  'path': [('body', 1), ('body', 18), ('body', 5), ('handlers', 0), ('body', 1)],
  'kind': 'safe_log'},
 {'line': 797,
  'function': 'auto_soften_aging_memories',
  'path': [('body', 1), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 1461,
  'function': '_render_day_page',
  'path': [('body', 22), ('body', 3), ('body', 7), ('body', 1)],
  'kind': 'keep'},
 {'line': 1471,
  'function': '_render_day_page',
  'path': [('body', 22), ('body', 3), ('body', 9), ('body', 0)],
  'kind': 'length'},
 {'line': 1476,
  'function': '_render_day_page',
  'path': [('body', 22), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 1514,
  'function': 'check_and_generate_summaries',
  'path': [('body', 6), ('body', 6), ('body', 1)],
  'kind': 'summary'},
 {'line': 1516,
  'function': 'check_and_generate_summaries',
  'path': [('body', 6), ('body', 6), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 1543,
  'function': 'check_and_generate_summaries',
  'path': [('body', 9), ('body', 8), ('body', 1)],
  'kind': 'summary'},
 {'line': 1545,
  'function': 'check_and_generate_summaries',
  'path': [('body', 9), ('body', 8), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 1578,
  'function': 'check_and_generate_summaries',
  'path': [('body', 10), ('body', 14), ('body', 1)],
  'kind': 'summary'},
 {'line': 1580,
  'function': 'check_and_generate_summaries',
  'path': [('body', 10), ('body', 14), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 1613,
  'function': 'check_and_generate_summaries',
  'path': [('body', 12), ('body', 15), ('body', 1)],
  'kind': 'summary'},
 {'line': 1615,
  'function': 'check_and_generate_summaries',
  'path': [('body', 12), ('body', 15), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 1630,
  'function': 'check_and_generate_summaries',
  'path': [('body', 13), ('body', 4), ('body', 1), ('body', 1), ('body', 1)],
  'kind': 'summary'},
 {'line': 1632,
  'function': 'check_and_generate_summaries',
  'path': [('body', 13), ('body', 4), ('body', 1), ('body', 1), ('handlers', 0), ('body', 0)],
  'kind': 'safe_log'},
 {'line': 2072,
  'function': '_call_model_for_json',
  'path': [('body', 2), ('body', 3), ('body', 7), ('body', 1)],
  'kind': 'keep'}]
OBSERVATIONS=[]

# Dependency fault points are outside JSON parsing, so InvalidRequest exercises
# the registered business catch rather than a new decoder catch in stage B.
FAULTS={
 'E1':'app.len','D1':'app.get_recent_memories','D2':'app.delete_memory',
 'D3':'app.batch_delete_memories_guarded','D4':'app.get_pool','D5':'app.clear_all_memories',
 'D6':'db.get_memory_heat_report','D7':'app.get_pool','D8':'app.save_compression_summary',
 'D9':'app.get_pool','D10':'db.get_calendar_page','D11':'db.get_calendar_range',
 'D12':'db.get_invalid_calendar_period_pages','D13':'db.update_calendar_page_user_edit',
 'D14':'db.update_calendar_page_user_edit','D15':'db.delete_calendar_page',
 'D16':'db.create_comment','D17':'db.get_comments','D18':'db.delete_comment',
 'D19':'db.get_active_scenes','D20':'db.get_pool','D21':'app._get_factory_prompts',
 'D22':'app._get_factory_prompts','D23':'app.get_all_categories','D24':'app.create_category',
 'D25':'app.update_category','D26':'app.delete_category','D27':'app.get_tools_for_servers',
 'D28':'app.get_active_system_prompt','D29':'app.set_system_prompt_in_db',
 'D30':'db.search_chat_messages','D31':'app.sync_get_conversations',
 'D32':'app.sync_get_conversation','D33':'app.sync_create_conversation',
 'D34':'app.sync_upsert_conversation','D35':'app.sync_patch_conversation',
 'D36':'app.sync_upsert_single_message','D37':'app.sync_get_projects',
 'D38':'app.sync_create_project','D39':'app.sync_upsert_project',
 'D40':'app.sync_patch_project','D41':'app.sync_delete_project',
 'D42':'db.delete_file_chunks','D43':'app.set_config','D44':'app.get_reminders',
 'D45':'app.create_reminder','D46':'app.get_due_reminders','D47':'app.get_reminders',
 'D48':'app.update_reminder','D49':'app.delete_reminder',
}
PAYLOADS={
 'D3':{'ids':[1]},'D4':{'ids':[1],'importance':5},
 'D5':{'force':True,'confirm':'DELETE_ALL_MEMORIES'},
 'D8':{'conversation_id':'fixture','summary':'synthetic'},
 'D13':{'type':'day'},'D14':{'type':'day'},
 'D16':{'target_type':'day_page','target_id':1,'content':'synthetic'},
 'D24':{'name':'fixture'},'D27':{'servers':[{'name':'fixture','url':'https://fixture.invalid'}]},
 'D33':{'id':'fixture'},'D38':{'id':'fixture'},'D43':{'user_nickname':'fixture'},
}

def concrete(route):
    method,path=route.split(' ',1)
    import re
    values={'date':'2026-09-18','key':'default_digest_model','memory_id':'1','category_id':'1',
            'comment_id':'1','dream_id':'1','provider_id':'1','model_id':'1','rid':'fixture',
            'conv_id':'fixture','msg_id':'fixture','proj_id':'fixture','file_id':'fixture'}
    return method,re.sub(r'\{([^}]+)\}',lambda m:values.get(m[1],'1'),path)

@contextmanager
def capture(level=logging.INFO):
    stdout,stderr,logs=io.StringIO(),io.StringIO(),io.StringIO()
    root=logging.getLogger();previous=root.level;handler=logging.StreamHandler(logs)
    root.addHandler(handler);root.setLevel(level)
    try:
        with redirect_stdout(stdout),redirect_stderr(stderr):yield stdout,stderr,logs
    finally:root.removeHandler(handler);root.setLevel(previous)

@contextmanager
def traced(filename,function):
    hits=[];old=sys.gettrace()
    def trace(frame,event,arg):
        if event=='line' and Path(frame.f_code.co_filename)==ROOT/filename and frame.f_code.co_name==function:
            hits.append(frame.f_lineno)
        return trace
    sys.settrace(trace)
    try:yield hits
    finally:sys.settrace(old)

def target_return(row):
    tree=ast.parse((ROOT/'main.py').read_text(encoding='utf8'))
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==row['function'])
    handlers=[n for n in ast.walk(fn) if isinstance(n,ast.ExceptHandler) and isinstance(n.type,ast.Name) and n.type.id==row['catch']]
    # X1 is the string-input catch; THINK-02 adds a later object-input catch.
    handler=(min if row['id']=='X1' else max)(handlers,key=lambda n:n.lineno)
    return max((n for n in ast.walk(handler) if isinstance(n,ast.Return)),key=lambda n:n.lineno).lineno

class FakePool:
    def __init__(self,rows=None):self.rows=rows or []
    def acquire(self):return self
    def transaction(self):return self
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def fetch(self,*args):return self.rows
    async def fetchrow(self,*args):return None
    async def fetchval(self,*args):return 0
    async def execute(self,*args):return 'UPDATE 0'

def find_raw_exception_returns(source_text):
    tree=ast.parse(source_text);bad=[]
    for fn in tree.body:
        if not isinstance(fn,(ast.AsyncFunctionDef,ast.FunctionDef)):continue
        if not any(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id=='app' for d in fn.decorator_list):continue
        for handler in (h for h in ast.walk(fn) if isinstance(h,ast.ExceptHandler) and h.name):
            for ret in (n for n in ast.walk(handler) if isinstance(n,ast.Return)):
                raw=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='str' and any(isinstance(a,ast.Name) and a.id==handler.name for a in n.args) or isinstance(n,ast.JoinedStr) and any(isinstance(x,ast.FormattedValue) and isinstance(x.value,ast.Name) and x.value.id==handler.name for x in n.values) for n in ast.walk(ret))
                literal_param=any(isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='param' and isinstance(v,ast.Constant) and v.value=='reasoning_effort' for k,v in zip(n.keys,n.values)) for n in ast.walk(ret))
                # The helper form is allowed only around the two input validators,
                # with the matching literal parameter; unrelated exceptions fail.
                helper_param = None
                call = ret.value
                if (isinstance(call,ast.Call) and isinstance(call.func,ast.Name)
                        and call.func.id=='_reasoning_400' and len(call.args)==2
                        and not call.keywords and isinstance(call.args[1],ast.Constant)):
                    helper_param = call.args[1].value
                validator = {'reasoning_effort':'_normalize_reasoning_effort',
                             'reasoning':'_parse_reasoning_object'}.get(helper_param)
                parent = next((n for n in ast.walk(fn) if isinstance(n,ast.Try) and handler in n.handlers),None)
                validated = bool(validator and parent and len(parent.body)==1
                    and isinstance(parent.body[0],ast.Assign)
                    and isinstance(parent.body[0].value,ast.Call)
                    and isinstance(parent.body[0].value.func,ast.Name)
                    and parent.body[0].value.func.id==validator)
                x1=fn.name=='chat_completions' and isinstance(handler.type,ast.Name) and handler.type.id=='ValueError' and (literal_param or validated)
                if raw and not x1:bad.append((fn.name,ret.lineno,'raw_exception'))
    return bad

class ErrGuards(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        # Real I/O forbidden by default; model tests explicitly replace transport.
        async def forbid(*args,**kwargs):raise AssertionError('FIXTURE: unexpected external HTTP')
        self.stack.enter_context(patch.object(httpx.AsyncHTTPTransport,'handle_async_request',forbid))
        self.stack.enter_context(patch.object(app,'get_memory_enabled',AsyncMock(return_value=True)))
        self.stack.enter_context(patch.object(app,'_legacy_write_gate',AsyncMock(return_value=None)))
        self.stack.enter_context(patch.object(app,'get_pool',AsyncMock(return_value=FakePool())))
        self.stack.enter_context(patch.object(db,'get_pool',AsyncMock(return_value=FakePool())))
        self.stack.enter_context(patch.object(config,'get_pool',AsyncMock(return_value=FakePool())))
        self.client=REAL_CLIENT(transport=httpx.ASGITransport(app=app.app,raise_app_exceptions=False),base_url='http://localhost')
        self.addAsyncCleanup(self.client.aclose)

    def outcome(self,case,response,streams,code,status,**metadata):
        issues=[]
        try:body=response.json()
        except (ValueError,UnicodeError):body=response.text
        if response.status_code!=status:issues.append(f'HTTP {response.status_code} != {status}')
        if body!={'error':code,'error_code':code}:issues.append(f'body {body!r} != stable {code}')
        channels=[response.text]+[s.getvalue() for s in streams]
        leaking=[name for name,text in zip(('response','stdout','stderr','root'),channels) if SENTINEL in text]
        if leaking:issues.append('sentinel in '+','.join(leaking))
        OBSERVATIONS.append(dict(case=case,status=response.status_code,body=body,leaking=leaking,issues=issues,**metadata))
        self.assertFalse(issues,case+': '+'; '.join(issues))

    async def exit_case(self,row,kind):
        case='T02_'+row['id']+'_'+kind
        exc={'runtime':RuntimeError,'invalid':security.InvalidRequest,'timeout':httpx.TimeoutException}[kind](SENTINEL)
        owner,name=FAULTS[row['id']].split('.');module={'app':app,'db':db}[owner]
        if row['id']=='E1':
            def fault(value):
                if value=='fixture-text':raise exc
                return len(value)
            mock=Mock(side_effect=fault)
        else:mock=(Mock if row['id'] in ('D21','D22') else AsyncMock)(side_effect=exc)
        method,path=concrete(row['route']);kwargs={'json':PAYLOADS.get(row['id'],{})}
        if row['id']=='E1':kwargs={'files':{'file':('fixture.txt',b'fixture-text','text/plain')}}
        if row['id']=='D9':kwargs['params']={'conversation_id':'fixture'}
        if row['id']=='D17':kwargs['params']={'target_type':'day_page','target_id':1}
        with patch.object(module,name,mock,create=row['id']=='E1'),capture() as streams,traced('main.py',row['function']) as hits:
            r=await self.client.request(method,path,**kwargs)
        target=target_return(row)
        self.assertTrue(mock.called,case+': FIXTURE fault not called')
        self.assertIn(target,hits,case+': FIXTURE wrong return '+str(hits))
        code,status={'runtime':('internal_error',500),'invalid':('invalid_request',400),'timeout':('timeout',502)}[kind]
        self.outcome(case,r,streams,code,status,function=row['function'],patch=FAULTS[row['id']],
                     preconditions='memory enabled; legacy gate open; valid body; fake DB',baseline_return=row['line'],hit_return=target)

    async def test_T02_D13_calendar_validation(self):
        row=next(r for r in EXITS if r['id']=='D13')
        with capture() as streams,traced('main.py',row['function']) as hits,patch.object(db,'update_calendar_page_user_edit',AsyncMock()) as write:
            r=await self.client.put('/admin/calendar/2026-09-18',json={'type':'week'})
        self.assertFalse(write.called,'FIXTURE invalid week must fail before DB')
        target=target_return(row);self.assertIn(target,hits)
        self.outcome('T02_D13_calendar_validation',r,streams,'invalid_request',400,patch='none: Friday used as week start',
                     preconditions='valid JSON; real calendar validation',baseline_return=row['line'],hit_return=target)

    async def x1(self,object_value):
        case='T02_X1_'+('object' if object_value else 'string')
        value={'k':SENTINEL} if object_value else SENTINEL+'x'*(200-len(SENTINEL))
        row=next(r for r in EXITS if r['id']=='X1')
        with capture() as streams,traced('main.py','chat_completions') as hits,patch.object(app,'resolve_provider_for_model',AsyncMock(side_effect=AssertionError('upstream forbidden'))) as routing:
            r=await self.client.post('/v1/chat/completions',json={'model':'fixture','messages':[],'reasoning_effort':value})
        self.assertIn(target_return(row),hits,'FIXTURE wrong X1 return');routing.assert_not_called()
        body=r.json();err=body.get('error',{});issues=[]
        if r.status_code!=400:issues.append('not 400')
        if not isinstance(err,dict) or set(err)!={'message','type','param','code'}:issues.append('wrong nested shape')
        if isinstance(err,dict):
            if err.get('param')!='reasoning_effort':issues.append('param missing')
            if '/'.join(config.REASONING_EFFORT_VALUES) not in err.get('message',''):issues.append('allowed values missing')
        if any(SENTINEL in s for s in [r.text]+[x.getvalue() for x in streams]):issues.append('client value echoed')
        OBSERVATIONS.append(dict(case=case,body=body,status=r.status_code,issues=issues,hit_return=target_return(row),baseline_return=row['line'],patch='resolve_provider_for_model forbidden',preconditions='invalid effort before routing'))
        self.assertFalse(issues,case+': '+str(issues))
    async def test_T02_X1_string(self):await self.x1(False)
    async def test_T02_X1_object(self):await self.x1(True)

    async def json_case(self,point,encoding,route=None):
        raw=b'{' if encoding=='json' else b'\xff'
        case=f"T05_{point['line']}_{encoding}"+('_'+route.split(' ')[0]+'_'+route.split(' ')[1].replace('/','_') if route else '')
        selected=route or point['routes'][0]
        method,path=concrete(selected)
        async def no_dream(*args,**kwargs):
            yield {'type':'done','data':'fixture'}
        with ExitStack() as st,capture() as streams,traced('main.py',point['function']) as hits:
            st.enter_context(patch.object(dream,'run_dream',no_dream))
            st.enter_context(patch.object(app,'_dream_is_running',AsyncMock(return_value=False)))
            st.enter_context(patch.object(app,'_launch_dream_detached',Mock()))
            st.enter_context(patch.object(app,'get_extract_interval',AsyncMock(return_value=10)))
            st.enter_context(patch.object(app,'snapshot_recent_conversation',AsyncMock(return_value={'rows':[]})))
            if point['call']=='json.loads':
                import re
                member=re.search(r'"([^\"]+\.json)"',point['source']).group(1)
                buf=io.BytesIO()
                with zipfile.ZipFile(buf,'w') as z:z.writestr(member,raw)
                r=await self.client.post(path,files={'file':('fixture.zip',buf.getvalue(),'application/zip')})
            else:r=await self.client.request(method,path,content=raw,headers={'Content-Type':'application/json'})
        # Current decoder line shifts after B; source identity is the handler/helper,
        # recorded baseline lines are only evidence, not a future line-number gate.
        self.assertTrue(hits,case+': FIXTURE decoder function not executed')
        self.outcome(case,r,streams,'invalid_request',400,parse_line=point['line'],route=selected,trace_lines=hits)

    async def optional_empty(self,kind):
        async def no_dream(*args,**kwargs):
            yield {'type':'done','data':'fixture'}
        routes={'clear':'DELETE /debug/memories','extract':'POST /admin/extract-now',
                'dream':'POST /dream/start','detached':'POST /dream/start-detached'}
        expected={'clear':(400,{'error':"清空全部记忆需同时携带 JSON force=true 与 confirm='DELETE_ALL_MEMORIES'"}),
                  'extract':(200,{'status':'ok','action':'extract','saved':0,'skipped':0,'message':'没有最近的对话可提取'}),
                  'dream':(200,'event: done\ndata: fixture\n\n'),
                  'detached':(200,{'status':'started'})}
        with ExitStack() as st:
            st.enter_context(patch.object(dream,'run_dream',no_dream))
            st.enter_context(patch.object(app,'_dream_is_running',AsyncMock(return_value=False)))
            st.enter_context(patch.object(app,'_launch_dream_detached',Mock()))
            st.enter_context(patch.object(app,'get_extract_interval',AsyncMock(return_value=10)))
            st.enter_context(patch.object(app,'snapshot_recent_conversation',AsyncMock(return_value={'rows':[]})))
            method,path=routes[kind].split(' ',1)
            response=await self.client.request(method,path,content=b'')
        actual=response.text if kind=='dream' else response.json()
        self.assertEqual((response.status_code,actual),expected[kind])
        OBSERVATIONS.append({'case':'T05_empty_'+kind,'status':response.status_code,'body':actual,'request_body_bytes':0})

    def test_T06_unknown_code(self):
        response=security.stable_error('not_in_whitelist')
        self.assertEqual(json.loads(response.body),{'error':'internal_error','error_code':'internal_error'})
        self.assertEqual(response.status_code,500,'T06: normalized unknown code must use HTTP 500')

    async def fixed(self,kind):
        with capture() as streams:
            if kind=='provider':r=await self.client.post('/admin/providers',json={'name':'','api_base_url':'https://fixture.invalid'})
            elif kind=='query':r=await self.client.post('/admin/search-test',json={'query':''})
            else:r=await self.client.post('/sync/import-backup',files={'file':('bad.zip',b'not a zip','application/zip')})
        self.outcome('T07_'+kind,r,streams,'invalid_request',400)
    async def test_T07_provider(self):await self.fixed('provider')
    async def test_T07_query(self):await self.fixed('query')
    async def test_T07_zip(self):await self.fixed('zip')

    def test_T01_source_main(self):
        self.assertEqual(find_raw_exception_returns((ROOT/'main.py').read_text(encoding='utf8')), [], 'T01: raw exception HTTP returns remain')

    def test_T01_source_daily(self):
        tree=ast.parse((ROOT/'daily_digest.py').read_text(encoding='utf8'))
        bad=[n.lineno for n in ast.walk(tree) if isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='error' and isinstance(v,ast.Call) and isinstance(v.func,ast.Name) and v.func.id=='str' for k,v in zip(n.keys,n.values))]
        self.assertEqual(bad,[],'T01: raw internal error dictionaries remain')

    def detector_sample(self,name,source,expected):
        fn=getattr(sys.modules[__name__],'find_raw_exception_returns',None)
        self.assertTrue(callable(fn),'T01b missing test-local seam find_raw_exception_returns: '+name)
        hits=fn(source)
        self.assertEqual(bool(hits),expected,name)
        for hit in hits:self.assertEqual(len(hit),3)

    def test_T01b_reasoning_helper_boundary(self):
        template = ('@app.post("/v1/chat/completions")\nasync def {function}():\n'
                    '    try: result = {validator}(body)\n'
                    '    except {exception} as e:\n'
                    '        return _reasoning_400(str(e), "{param}")\n')
        for function, validator, exception, param, bad in [
            ('chat_completions','_normalize_reasoning_effort','ValueError','reasoning_effort',False),
            ('chat_completions','_parse_reasoning_object','ValueError','reasoning',False),
            ('chat_completions','untrusted_work','ValueError','reasoning',True),
            ('chat_completions','_parse_reasoning_object','Exception','reasoning',True),
            ('chat_completions','_parse_reasoning_object','ValueError','other',True),
            ('other_route','_parse_reasoning_object','ValueError','reasoning',True),
        ]:
            with self.subTest(function=function,validator=validator,exception=exception,param=param):
                self.detector_sample('reasoning-helper',template.format(
                    function=function,validator=validator,exception=exception,param=param),bad)

    async def test_T10_memory_disabled(self):
        with patch.object(app,'get_memory_enabled',AsyncMock(return_value=False)):
            r=await self.client.get('/admin/embedding-stats')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json(),{'error':'记忆系统未启用'})

    def test_T10_w2_fixed_responses(self):
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf8'))
        expected={'api_sync_import':{'error':'导入失败'},'api_sync_delete_conversation':{'error':'删除失败'},
                  'api_sync_reset':{'error':'重置失败'}}
        all_literals=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Dict):
                try:all_literals.append(ast.literal_eval(n))
                except (ValueError,TypeError):pass
        for value in list(expected.values())+[{'error':'invalid_project_id','code':'invalid_project_id'}]:
            self.assertIn(value,all_literals)

    async def test_T10_sources_changed(self):
        with patch.object(app,'save_compression_summary',AsyncMock(return_value=('对话素材已变化',409,'sources_changed'))):
            r=await self.client.post('/admin/compression-summary',json={'conversation_id':'fixture','summary':'synthetic'})
        self.assertEqual(r.status_code,409)
        self.assertEqual(r.json(),{'error':'对话素材已变化','code':'sources_changed'})

    async def test_T10_probe_diagnostic_contract(self):
        import embedding_probe
        payload={'ok':False,'error_code':'invalid_response'}
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=object())),patch.object(embedding_probe,'probe_embedding',AsyncMock(return_value=payload)):
            r=await self.client.post('/admin/embedding-probe')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json(),payload)

    async def tcp_trace(self,level):
        async def server(reader,writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 502 '+SENTINEL.encode()+b'\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain();writer.close();await writer.wait_closed()
        srv=await asyncio.start_server(server,'127.0.0.1',0)
        # Explicit real transport only for loopback; overriding class method mock
        # uses the original implementation saved before fixtures were installed.
        records=[]
        class Handler(logging.Handler):
            def emit(self,record):records.append((record.name,record.getMessage()))
        handler=Handler();root=logging.getLogger();root.addHandler(handler)
        try:
            with capture(level) as streams,patch.object(httpx.AsyncHTTPTransport,'handle_async_request',REAL_TRANSPORT):
                async with REAL_CLIENT(trust_env=False) as client:
                    r=await client.get(f'http://127.0.0.1:{srv.sockets[0].getsockname()[1]}/fixture')
            self.assertEqual(r.status_code,502)
        finally:root.removeHandler(handler);srv.close();await srv.wait_closed()
        name='httpcore.http11' if level==logging.DEBUG else 'httpx'
        relevant=[msg for logger,msg in records if logger==name and ('receive_response_headers.complete' in msg if level==logging.DEBUG else 'HTTP Request:' in msg)]
        self.assertTrue(relevant,'T08: actual transport record must be captured')
        self.assertTrue(any('502' in msg for msg in relevant))
        self.assertNotIn(SENTINEL,'\n'.join(relevant),'T08: upstream reason leaked')
    async def test_T08_http11_debug(self):await self.tcp_trace(logging.DEBUG)
    async def test_T08_httpx_info(self):await self.tcp_trace(logging.INFO)
    async def test_T08_http2_unchanged(self):
        from httpcore._trace import Trace
        with capture(logging.DEBUG) as streams:
            await Trace('receive_response_headers',logging.getLogger('httpcore.http2')).atrace('receive_response_headers.complete',{'return_value':(502,[(b'fixture',b'header')])})
        self.assertIn("return_value=(502, [(b'fixture', b'header')])",streams[2].getvalue())

    async def daily_case(self,family,mode):
        case='T03_'+family+'_'+mode
        now=datetime(2026,9,18,12,tzinfo=timezone.utc)
        rows=[{'id':i,'title':'fixture','content':'synthetic','importance':5,'created_at':now} for i in range(3)]
        pool=FakePool(rows if family=='digest' else [])
        calls=[]
        def upstream(request):
            calls.append(request)
            if mode=='exception':raise RuntimeError(SENTINEL)
            if mode=='timeout':raise httpx.ReadTimeout(SENTINEL)
            if mode=='http':return httpx.Response(500,text=SENTINEL)
            if mode=='bad_json':return httpx.Response(200,text='{'+SENTINEL)
            text='' if mode=='empty' else SENTINEL
            return httpx.Response(200,json={'choices':[{'message':{'content':text},'finish_reason':'length' if mode=='length' else 'stop'}],'usage':{'completion_tokens':6000}})
        def model_client(**kwargs):return REAL_CLIENT(transport=httpx.MockTransport(upstream),**kwargs)
        with ExitStack() as st,capture() as streams:
            st.enter_context(patch.object(db,'get_pool',AsyncMock(return_value=pool)))
            st.enter_context(patch.object(db,'get_all_categories',AsyncMock(return_value=[])))
            st.enter_context(patch.object(config,'get_config',AsyncMock(return_value='')))
            st.enter_context(patch.object(config,'get_config_bool',AsyncMock(return_value=True)))
            st.enter_context(patch.object(config,'get_config_int',AsyncMock(return_value=10)))
            st.enter_context(patch.object(db,'resolve_model_endpoint',AsyncMock(return_value=('https://fixture.invalid/v1/chat/completions','synthetic-key','openai'))))
            st.enter_context(patch.object(httpx,'AsyncClient',model_client))
            if family in ('scene','retire'):
                fault=st.enter_context(patch.object(db,'get_pool',AsyncMock(side_effect=RuntimeError(SENTINEL))))
                result=await (daily.backfill_scene_embeddings() if family=='scene' else daily.retire_stale_locks())
                fault.assert_awaited_once()
            elif family=='soften':
                fault=st.enter_context(patch.object(db,'get_aging_memories',AsyncMock(side_effect=RuntimeError(SENTINEL))))
                result=await daily.auto_soften_aging_memories(model_override='fixture');fault.assert_awaited_once()
            elif family=='digest':result=await daily._run_daily_digest_impl('2026-09-18',now,model_override='fixture')
            elif family=='profile':result=await daily.update_user_profile(digest_text='synthetic',model_override='fixture')
            elif family=='day':
                result=await daily._render_day_page('2026-09-18',[],model_override='fixture')
                self.assertIsInstance(result,tuple);self.assertEqual(len(result),3)
                self.assertIsNone(result[0]);self.assertEqual(result[2],'fixture');result=result[1]
            elif family=='date_digest':result=await daily.run_daily_digest(SENTINEL)
            else:result=await daily._generate_day_page_impl(SENTINEL)
        if family in ('digest','profile','day'):self.assertEqual(len(calls),1,'FIXTURE model path not called')
        code='invalid_request' if family.startswith('date_') else {'exception':'internal_error','timeout':'timeout','http':'http_500','bad_json':'parse_failed','invalid':'parse_failed','length':'parse_failed','empty':'upstream_error'}[mode]
        preserved={'digest':{'date':'2026-09-18','fragments':3,'digests':0},'profile':{'status':'error'},'scene':{'status':'error','backfilled':0,'skipped':0},'retire':{'status':'error','retired':0},'soften':{'status':'error','softened':0,'skipped':0},'day':{'date':'2026-09-18','status':'error'},'date_digest':{},'date_day':{}}[family]
        issues=[]
        if result!={**preserved,'error':code,'error_code':code}:issues.append('wrong result '+repr(result))
        leaking=[name for name,text in zip(('result','stdout','stderr','root'),[json.dumps(result)]+[s.getvalue() for s in streams]) if SENTINEL in text]
        if leaking:issues.append('sentinel in '+','.join(leaking))
        OBSERVATIONS.append(dict(case=case,result=result,leaking=leaking,issues=issues))
        self.assertFalse(issues,case+': '+'; '.join(issues))

    def summary_case(self,kind):
        fn=getattr(security,'public_model_summary',None)
        self.assertTrue(callable(fn),'T03 missing callable security.public_model_summary: '+kind)
        value,expected={
            'error_key':({'error':SENTINEL,'status':'error','error_code':'timeout'},{'status':'error','error_code':'timeout'}),
            'bad_date':({'date':SENTINEL},{}),
            'bool_count':({'digests':True,'fragments':False},{}),
            'unknown_status':({'status':SENTINEL},{}),
            'valid':({'date':'2026-09-18','status':'ok','digests':2,'backfilled':0},{'date':'2026-09-18','status':'ok','digests':2,'backfilled':0}),
            'unknown_code':({'error_code':SENTINEL},{'error_code':'internal_error'}),
        }[kind]
        self.assertEqual(fn(value),expected,kind)

    def daily_log_case(self,row):
        # Evaluate the actual production logging statement in isolation. This
        # covers logger value handling, not scheduler timing/control flow.
        tree=ast.parse((ROOT/'daily_digest.py').read_text(encoding='utf8'))
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==row['function'])
        for field,index in row['path']:
            node=getattr(node,field)
            if index is not None:node=node[index]
        self.assertIsInstance(node,ast.Expr,'FIXTURE log statement path changed')
        names={n.id for n in ast.walk(node) if isinstance(n,ast.Name)}
        if 'public_model_summary' in names:
            self.assertTrue(callable(getattr(security,'public_model_summary',None)),'T03 log missing public_model_summary')
        env=dict(vars(daily),safe_log=security.safe_log,public_model_summary=getattr(security,'public_model_summary',None),
                 e=RuntimeError(SENTINEL),text=SENTINEL,scene_id=1,mem_id=1,max_tokens=6000,usage={'completion_tokens':6000})
        for name in names:
            if 'result' in name:env[name]={'status':'error','error':SENTINEL,'error_code':'timeout','date':'2026-09-18','digests':0}
        with capture() as streams:exec(compile(ast.Module(body=[node],type_ignores=[]),'daily-log-expression','exec'),env)
        log='\n'.join(s.getvalue() for s in streams)
        self.assertNotIn(SENTINEL,log,'T03 log raw text: '+str(row['line']))

    def test_T10_calendar_failure_dicts(self):
        tree=ast.parse((ROOT/'daily_digest.py').read_text(encoding='utf8'))
        for name in ('generate_week_summary','generate_month_summary','generate_period_summary'):
            fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
            values=[]
            for node in ast.walk(fn):
                if isinstance(node,ast.Return):
                    try:values.append(ast.literal_eval(node.value))
                    except (TypeError,ValueError):pass
            self.assertIn({'status':'error','error':'model returned invalid format'},values,name)

    async def test_T05_upstream_bad_json(self):
        # Existing S-class route: invalid upstream JSON retains parse_failed 502.
        def upstream(request):return httpx.Response(200,text='{')
        with patch.object(app,'get_provider',AsyncMock(return_value={'id':1,'name':'fixture','api_key':'synthetic','api_base_url':'https://fixture.invalid/v1','api_format':'openai'})),patch.object(httpx,'AsyncClient',lambda **kw:REAL_CLIENT(transport=httpx.MockTransport(upstream),**kw)),capture() as streams:
            r=await self.client.get('/admin/providers/1/models')
        self.outcome('T05_upstream_bad_json',r,streams,'parse_failed',502)

    async def test_T10_x1_parameter_diagnostics(self):
        with patch.object(app,'resolve_provider_for_model',AsyncMock(side_effect=AssertionError('routing forbidden'))) as routing:
            r=await self.client.post('/v1/chat/completions',json={'model':'fixture','messages':[],'reasoning_effort':'ultra'})
        self.assertEqual(r.status_code,400);routing.assert_not_called()
        self.assertEqual(r.json()['error']['param'],'reasoning_effort')
        self.assertIn('/'.join(config.REASONING_EFFORT_VALUES),r.json()['error']['message'])

    def test_T09_sec_logging_calibration(self):
        import subprocess
        result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/test_kiwi_sec_01a.py')],
                              cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace',
                              env=dict(os.environ,PYTHONUTF8='1'),timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 37 tests',result.stderr)

REAL_TRANSPORT=httpx.AsyncHTTPTransport.handle_async_request

def install_cases():
    for row in LOG_ROWS:
        def test(self,row=row):self.daily_log_case(row)
        group='T10' if row['kind']=='keep' else 'T03'
        setattr(ErrGuards,'test_'+group+'_log_'+str(row['line']),test)
    daily_cases=[('digest','exception'),('profile','exception'),('scene','exception'),('retire','exception'),('soften','exception'),('day','exception'),('digest','http'),('profile','http'),('day','http'),('digest','invalid'),('profile','empty'),('day','length'),('day','invalid'),('date_digest','invalid'),('date_day','invalid')]
    daily_cases += [(family,mode) for family in ('digest','profile','day') for mode in ('timeout','bad_json')]
    for family,mode in daily_cases:
        async def test(self,family=family,mode=mode):await self.daily_case(family,mode)
        setattr(ErrGuards,'test_T03_'+family+'_'+mode,test)
    for kind in ('error_key','bad_date','bool_count','unknown_status','valid','unknown_code'):
        def test(self,kind=kind):self.summary_case(kind)
        setattr(ErrGuards,'test_T03_summary_'+kind,test)
    for row in EXITS:
        if row['id']=='X1':continue
        kinds=('invalid',) if row['id']=='D13' else ('runtime','timeout') if row['id']=='D14' else ('runtime','invalid','timeout')
        for kind in kinds:
            async def test(self,row=row,kind=kind):await self.exit_case(row,kind)
            setattr(ErrGuards,'test_T02_'+row['id']+'_'+kind,test)
    for code,status in [('invalid_request',400),('http_502',502),('timeout',502),('parse_failed',502),('internal_error',500),('upstream_error',502),('missing',502),('unknown',502)]:
        def test(self,code=code,status=status):
            payload={'status':'error','error':SENTINEL}
            if code!='missing':payload['error_code']=code
            response=security.public_model_result(payload)
            normalized=code if code not in ('missing','unknown') else 'upstream_error'
            self.assertEqual((response.status_code,json.loads(response.body)),(status,{'error':normalized,'error_code':normalized}),code)
        setattr(ErrGuards,'test_T04_'+code,test)
    shared=['POST /sync/conversations','PATCH /sync/conversations/{conv_id}','PUT /sync/conversations/{conv_id}/messages/{msg_id}','POST /sync/projects','PATCH /sync/projects/{proj_id}','POST /sync/import']
    for point in PARSES:
        routes=shared if point['function']=='_read_json_object' else [None]
        for number,route in enumerate(routes):
            for encoding in ('json','utf8'):
                async def test(self,point=point,encoding=encoding,route=route):await self.json_case(point,encoding,route)
                setattr(ErrGuards,f"test_T05_{point['line']}_{number}_{encoding}",test)
    for kind in ('clear','extract','dream','detached'):
        async def test(self,kind=kind):await self.optional_empty(kind)
        setattr(ErrGuards,'test_T05_empty_'+kind,test)
    fragments={
        'str':('return {"error": str(e)}',True),
        'fstring':('return {"error": f"oops {e}"}',True),
        'response':('return JSONResponse(content={"error": str(e)})',True),
        'stable':('return stable_error(e)',False),
        'fixed':('return {"error":"x"}',False),
    }
    for name,(ret,hit) in fragments.items():
        source='@app.get("/fixture")\nasync def handler():\n    try: await work()\n    except Exception as e:\n        '+ret+'\n'
        def test(self,name=name,source=source,hit=hit):self.detector_sample(name,source,hit)
        setattr(ErrGuards,'test_T01b_'+name,test)
    source='@app.post("/v1/chat/completions")\nasync def chat_completions():\n    try: work()\n    except ValueError as e:\n        return JSONResponse(content={"error":{"message":str(e),"param":"reasoning_effort"}})\n'
    def x1(self):self.detector_sample('x1',source,False)
    setattr(ErrGuards,'test_T01b_x1',x1)
install_cases()

class EvidenceResult(unittest.TextTestResult):
    def startTest(self,test):super().startTest(test);self.started=str(test)
    def addSuccess(self,test):super().addSuccess(test);RESULTS.append({'test':test._testMethodName,'outcome':'PASS'})
    def addFailure(self,test,err):super().addFailure(test,err);RESULTS.append({'test':test._testMethodName,'outcome':'FAIL','reason':self._exc_info_to_string(err,test)})
    def addError(self,test,err):super().addError(test,err);RESULTS.append({'test':test._testMethodName,'outcome':'ERROR','reason':self._exc_info_to_string(err,test)})
RESULTS=[]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence');parser.add_argument('--filter',default='')
    args=parser.parse_args()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ErrGuards)
    if args.filter:suite=unittest.TestSuite(t for t in suite if args.filter in t._testMethodName)
    result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(suite)
    if args.evidence:Path(args.evidence).write_text(json.dumps({'baseline':BASE,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'results':RESULTS,'observations':OBSERVATIONS},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    sys.exit(0 if result.wasSuccessful() else 1)
