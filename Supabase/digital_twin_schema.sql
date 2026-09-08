-- ============================================================
-- WearTwin Database Schema v2 — Idempotent Update
-- Run in Supabase SQL Editor (safe to re-run)
-- Changes: RLS anon-read policies, anomaly_flags trigger,
--          activity_level extraction, data TTL cleanup function
-- ============================================================

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------
-- TABLES (unchanged — idempotent)
-- ---------------------------------------------------------------
create table if not exists public.patient_profiles (
    id uuid primary key default uuid_generate_v4(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    full_name text,
    age integer check (age between 0 and 130),
    gender text check (gender in ('male','female','other','unknown')),
    bmi numeric(4,1),
    family_history boolean default false,
    medical_notes text,
    device_id text unique
);

create table if not exists public.twin_states (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    latest_hr numeric(5,2),
    latest_spo2 numeric(5,2),
    latest_temp numeric(5,2),
    latest_bp_systolic integer,
    latest_bp_diastolic integer,
    latest_activity_level numeric(4,2) default 5.0,
    rolling_avg_24h jsonb not null default '{}'::jsonb,
    rolling_avg_7d jsonb not null default '{}'::jsonb,
    risk_label text not null default 'low',
    risk_confidence numeric(5,2) not null default 0.00,
    anomaly_flags jsonb not null default '[]'::jsonb,
    status text not null default 'stable',
    unique(patient_id)
);

create table if not exists public.sensor_events (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    source text not null default 'wearable',
    payload jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.risk_history (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    recorded_at timestamptz not null default now(),
    risk_label text not null,
    risk_confidence numeric(5,2) not null default 0.00,
    shap_top_features jsonb not null default '{}'::jsonb
);

create table if not exists public.anomaly_flags (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    flag_type text not null,
    severity text not null default 'medium',
    description text,
    detected_at timestamptz not null default now(),
    resolved boolean not null default false
);

create table if not exists public.alerts (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    alert_type text not null,
    severity text not null default 'medium',
    message text not null,
    is_read boolean not null default false,
    created_at timestamptz not null default now()
);

-- Add activity_level column if not already present (safe migration)
alter table public.twin_states
    add column if not exists latest_activity_level numeric(4,2) default 5.0;

-- ---------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------
create index if not exists idx_twin_states_patient_id          on public.twin_states(patient_id);
create index if not exists idx_sensor_events_patient_created   on public.sensor_events(patient_id, created_at desc);
create index if not exists idx_sensor_events_created_at        on public.sensor_events(created_at desc);  -- TTL cleanup
create index if not exists idx_risk_history_patient_time       on public.risk_history(patient_id, recorded_at desc);
create index if not exists idx_anomaly_flags_patient           on public.anomaly_flags(patient_id, detected_at desc);
create index if not exists idx_alerts_patient                  on public.alerts(patient_id, created_at desc);

-- ---------------------------------------------------------------
-- UPDATED-AT TRIGGER
-- ---------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end; $$;

drop trigger if exists set_patient_profiles_updated_at on public.patient_profiles;
create trigger set_patient_profiles_updated_at
before update on public.patient_profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_twin_states_updated_at on public.twin_states;
create trigger set_twin_states_updated_at
before update on public.twin_states
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------
-- RLS ENABLE
-- ---------------------------------------------------------------
alter table public.patient_profiles enable row level security;
alter table public.twin_states      enable row level security;
alter table public.sensor_events    enable row level security;
alter table public.risk_history     enable row level security;
alter table public.anomaly_flags    enable row level security;
alter table public.alerts           enable row level security;

-- ---------------------------------------------------------------
-- RLS POLICIES
--
-- Design:
--   WRITE (insert/update/delete) — service_role only.
--     The backend server uses SUPABASE_SERVICE_KEY which bypasses
--     RLS entirely in Supabase (no policy needed for service_role).
--     These explicit policies are a defense-in-depth fallback.
--
--   READ (select) — open to anon role.
--     Allows the provider dashboard and API GET endpoints to fetch
--     twin states and patient lists without needing a JWT.
--     Restrict to authenticated in production after adding auth.
-- ---------------------------------------------------------------

-- patient_profiles
drop policy if exists "service_role_insert_patient_profiles" on public.patient_profiles;
drop policy if exists "service_role_update_patient_profiles" on public.patient_profiles;
drop policy if exists "service_role_delete_patient_profiles" on public.patient_profiles;
drop policy if exists "service_role_select_patient_profiles" on public.patient_profiles;
drop policy if exists "anon_select_patient_profiles"         on public.patient_profiles;

create policy "anon_select_patient_profiles"         on public.patient_profiles for select using (true);
create policy "service_role_insert_patient_profiles" on public.patient_profiles for insert with check (auth.role() = 'service_role');
create policy "service_role_update_patient_profiles" on public.patient_profiles for update using (auth.role() = 'service_role');
create policy "service_role_delete_patient_profiles" on public.patient_profiles for delete using (auth.role() = 'service_role');

-- twin_states
drop policy if exists "service_role_insert_twin_states" on public.twin_states;
drop policy if exists "service_role_update_twin_states" on public.twin_states;
drop policy if exists "service_role_delete_twin_states" on public.twin_states;
drop policy if exists "service_role_select_twin_states" on public.twin_states;
drop policy if exists "anon_select_twin_states"         on public.twin_states;

create policy "anon_select_twin_states"         on public.twin_states for select using (true);
create policy "service_role_insert_twin_states" on public.twin_states for insert with check (auth.role() = 'service_role');
create policy "service_role_update_twin_states" on public.twin_states for update using (auth.role() = 'service_role');
create policy "service_role_delete_twin_states" on public.twin_states for delete using (auth.role() = 'service_role');

-- sensor_events (raw telemetry — restrict reads to service_role)
drop policy if exists "service_role_select_sensor_events" on public.sensor_events;
drop policy if exists "service_role_insert_sensor_events" on public.sensor_events;
drop policy if exists "service_role_update_sensor_events" on public.sensor_events;
drop policy if exists "service_role_delete_sensor_events" on public.sensor_events;

create policy "service_role_select_sensor_events" on public.sensor_events for select using (auth.role() = 'service_role');
create policy "service_role_insert_sensor_events" on public.sensor_events for insert with check (auth.role() = 'service_role');
create policy "service_role_update_sensor_events" on public.sensor_events for update using (auth.role() = 'service_role');
create policy "service_role_delete_sensor_events" on public.sensor_events for delete using (auth.role() = 'service_role');

-- risk_history
drop policy if exists "service_role_select_risk_history" on public.risk_history;
drop policy if exists "service_role_insert_risk_history" on public.risk_history;
drop policy if exists "service_role_update_risk_history" on public.risk_history;
drop policy if exists "service_role_delete_risk_history" on public.risk_history;
drop policy if exists "anon_select_risk_history"         on public.risk_history;

create policy "anon_select_risk_history"         on public.risk_history for select using (true);
create policy "service_role_insert_risk_history" on public.risk_history for insert with check (auth.role() = 'service_role');
create policy "service_role_update_risk_history" on public.risk_history for update using (auth.role() = 'service_role');
create policy "service_role_delete_risk_history" on public.risk_history for delete using (auth.role() = 'service_role');

-- anomaly_flags
drop policy if exists "service_role_select_anomaly_flags" on public.anomaly_flags;
drop policy if exists "service_role_insert_anomaly_flags" on public.anomaly_flags;
drop policy if exists "service_role_update_anomaly_flags" on public.anomaly_flags;
drop policy if exists "service_role_delete_anomaly_flags" on public.anomaly_flags;
drop policy if exists "anon_select_anomaly_flags"         on public.anomaly_flags;

create policy "anon_select_anomaly_flags"         on public.anomaly_flags for select using (true);
create policy "service_role_insert_anomaly_flags" on public.anomaly_flags for insert with check (auth.role() = 'service_role');
create policy "service_role_update_anomaly_flags" on public.anomaly_flags for update using (auth.role() = 'service_role');
create policy "service_role_delete_anomaly_flags" on public.anomaly_flags for delete using (auth.role() = 'service_role');

-- alerts
drop policy if exists "service_role_select_alerts" on public.alerts;
drop policy if exists "service_role_insert_alerts" on public.alerts;
drop policy if exists "service_role_update_alerts" on public.alerts;
drop policy if exists "service_role_delete_alerts" on public.alerts;
drop policy if exists "anon_select_alerts"         on public.alerts;

create policy "anon_select_alerts"         on public.alerts for select using (true);
create policy "service_role_insert_alerts" on public.alerts for insert with check (auth.role() = 'service_role');
create policy "service_role_update_alerts" on public.alerts for update using (auth.role() = 'service_role');
create policy "service_role_delete_alerts" on public.alerts for delete using (auth.role() = 'service_role');

-- ---------------------------------------------------------------
-- CORE TRIGGER: process_sensor_event
-- Updated to:
--   1. Extract activity_level from payload
--   2. Detect anomalies and write to anomaly_flags table
--   3. Update twin_states with activity_level
-- ---------------------------------------------------------------
create or replace function public.process_sensor_event()
returns trigger language plpgsql as $$
declare
    v_hr              numeric;
    v_spo2            numeric;
    v_temp            numeric;
    v_bp_systolic     integer;
    v_bp_diastolic    integer;
    v_activity        numeric;
    avg_hr_24         numeric;
    avg_spo2_24       numeric;
    avg_temp_24       numeric;
    avg_hr_7d         numeric;
    avg_spo2_7d       numeric;
    avg_temp_7d       numeric;
    prev_hr           numeric;
    prev_spo2         numeric;
begin
    -- Extract vitals from JSONB payload
    if (NEW.payload ? 'hr')            then v_hr           := (NEW.payload->>'hr')::numeric;           end if;
    if (NEW.payload ? 'spo2')          then v_spo2         := (NEW.payload->>'spo2')::numeric;         end if;
    if (NEW.payload ? 'temp')          then v_temp         := (NEW.payload->>'temp')::numeric;         end if;
    if (NEW.payload ? 'bp_sys')        then v_bp_systolic  := (NEW.payload->>'bp_sys')::integer;       end if;
    if (NEW.payload ? 'bp_dia')        then v_bp_diastolic := (NEW.payload->>'bp_dia')::integer;       end if;
    if (NEW.payload ? 'activity_level') then v_activity    := (NEW.payload->>'activity_level')::numeric; end if;

    -- 24h rolling averages
    select avg((payload->>'hr')::numeric)   into avg_hr_24   from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '24 hours';
    select avg((payload->>'spo2')::numeric) into avg_spo2_24 from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '24 hours';
    select avg((payload->>'temp')::numeric) into avg_temp_24 from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '24 hours';

    -- 7d rolling averages
    select avg((payload->>'hr')::numeric)   into avg_hr_7d   from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '7 days';
    select avg((payload->>'spo2')::numeric) into avg_spo2_7d from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '7 days';
    select avg((payload->>'temp')::numeric) into avg_temp_7d from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '7 days';

    -- Fetch previous vitals for sudden-deviation detection
    select latest_hr, latest_spo2 into prev_hr, prev_spo2
    from public.twin_states where patient_id = NEW.patient_id;

    -- Upsert twin_states
    update public.twin_states set
        latest_hr              = coalesce(v_hr,           latest_hr),
        latest_spo2            = coalesce(v_spo2,         latest_spo2),
        latest_temp            = coalesce(v_temp,         latest_temp),
        latest_bp_systolic     = coalesce(v_bp_systolic,  latest_bp_systolic),
        latest_bp_diastolic    = coalesce(v_bp_diastolic, latest_bp_diastolic),
        latest_activity_level  = coalesce(v_activity,     latest_activity_level),
        rolling_avg_24h = jsonb_build_object(
            'hr',   round(coalesce(avg_hr_24,   latest_hr::numeric)::numeric, 2),
            'spo2', round(coalesce(avg_spo2_24, latest_spo2::numeric)::numeric, 2),
            'temp', round(coalesce(avg_temp_24, latest_temp::numeric)::numeric, 2)
        ),
        rolling_avg_7d = jsonb_build_object(
            'hr',   round(coalesce(avg_hr_7d,   latest_hr::numeric)::numeric, 2),
            'spo2', round(coalesce(avg_spo2_7d, latest_spo2::numeric)::numeric, 2),
            'temp', round(coalesce(avg_temp_7d, latest_temp::numeric)::numeric, 2)
        ),
        updated_at = now()
    where patient_id = NEW.patient_id;

    if not found then
        insert into public.twin_states (
            patient_id, latest_hr, latest_spo2, latest_temp,
            latest_bp_systolic, latest_bp_diastolic, latest_activity_level,
            rolling_avg_24h, rolling_avg_7d, risk_label, risk_confidence, anomaly_flags, status
        ) values (
            NEW.patient_id, v_hr, v_spo2, v_temp, v_bp_systolic, v_bp_diastolic,
            coalesce(v_activity, 5.0),
            jsonb_build_object('hr', avg_hr_24, 'spo2', avg_spo2_24, 'temp', avg_temp_24),
            jsonb_build_object('hr', avg_hr_7d,  'spo2', avg_spo2_7d,  'temp', avg_temp_7d),
            'pending', 0.0, '[]'::jsonb, 'unknown'
        );
    end if;

    -- -------------------------------------------------------
    -- Anomaly Detection (writes to anomaly_flags table)
    -- Thresholds chosen to match clinical early-warning scores
    -- -------------------------------------------------------

    -- Tachycardia (HR > 130 bpm)
    if v_hr is not null and v_hr > 130 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'tachycardia',
                case when v_hr > 150 then 'high' else 'medium' end,
                format('Heart rate %.1f bpm exceeds safe threshold (>130 bpm)', v_hr));
    end if;

    -- Bradycardia (HR < 45 bpm)
    if v_hr is not null and v_hr < 45 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'bradycardia', 'high',
                format('Heart rate %.1f bpm below safe threshold (<45 bpm)', v_hr));
    end if;

    -- Hypoxia (SpO2 < 92%)
    if v_spo2 is not null and v_spo2 < 92 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'hypoxia',
                case when v_spo2 < 88 then 'high' else 'medium' end,
                format('SpO2 %.1f%% below safe threshold (<92%%)', v_spo2));
    end if;

    -- Fever (temp > 38.3°C)
    if v_temp is not null and v_temp > 38.3 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'fever',
                case when v_temp > 39.5 then 'high' else 'medium' end,
                format('Temperature %.1f°C indicates fever (>38.3°C)', v_temp));
    end if;

    -- Hypertensive urgency (systolic BP > 170)
    if v_bp_systolic is not null and v_bp_systolic > 170 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'hypertension',
                case when v_bp_systolic > 190 then 'high' else 'medium' end,
                format('Systolic BP %s mmHg exceeds hypertensive threshold (>170)', v_bp_systolic));
    end if;

    -- Sudden HR spike: >25 bpm jump from previous reading
    if v_hr is not null and prev_hr is not null and abs(v_hr - prev_hr) > 25 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'sudden_hr_change', 'medium',
                format('Sudden HR change: %.1f → %.1f bpm (delta %.1f)', prev_hr, v_hr, v_hr - prev_hr));
    end if;

    -- Sudden SpO2 drop: >5% from previous reading
    if v_spo2 is not null and prev_spo2 is not null and (prev_spo2 - v_spo2) > 5 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'sudden_spo2_drop', 'high',
                format('Sudden SpO2 drop: %.1f%% → %.1f%% (delta %.1f%%)', prev_spo2, v_spo2, prev_spo2 - v_spo2));
    end if;

    -- Sedentary flag: activity_level < 1.5 (consistently inactive — T2D risk marker)
    if v_activity is not null and v_activity < 1.5 then
        insert into public.anomaly_flags (patient_id, flag_type, severity, description)
        values (NEW.patient_id, 'sedentary', 'low',
                format('Activity level %.1f/10 indicates prolonged sedentary state', v_activity));
    end if;

    -- Provisional risk row (backend ML overwrites this with real label)
    insert into public.risk_history (patient_id, risk_label, risk_confidence, shap_top_features)
    values (NEW.patient_id, 'pending', 0.0, '{}'::jsonb);

    -- Notify backend to run ML model
    perform pg_notify('sensor_event_received',
        json_build_object('patient_id', NEW.patient_id, 'event_id', NEW.id)::text);

    return NEW;
end;
$$;

drop trigger if exists process_sensor_event_trigger on public.sensor_events;
create trigger process_sensor_event_trigger
after insert on public.sensor_events
for each row execute function public.process_sensor_event();

-- ---------------------------------------------------------------
-- DATA TTL: Cleanup function + pg_cron schedule
-- Keeps last N days of sensor_events per patient.
-- Call manually: select public.cleanup_old_sensor_events(90);
-- ---------------------------------------------------------------
create or replace function public.cleanup_old_sensor_events(days_to_keep int default 90)
returns text language plpgsql as $$
declare
    deleted_count bigint;
begin
    delete from public.sensor_events
    where created_at < now() - (days_to_keep || ' days')::interval;
    get diagnostics deleted_count = row_count;
    return format('Deleted %s sensor_events older than %s days', deleted_count, days_to_keep);
end;
$$;

-- Also cleanup old resolved anomaly_flags (keep 30 days)
create or replace function public.cleanup_old_anomaly_flags(days_to_keep int default 30)
returns text language plpgsql as $$
declare deleted_count bigint;
begin
    delete from public.anomaly_flags
    where resolved = true and detected_at < now() - (days_to_keep || ' days')::interval;
    get diagnostics deleted_count = row_count;
    return format('Deleted %s resolved anomaly_flags older than %s days', deleted_count, days_to_keep);
end;
$$;

-- Schedule daily cleanup at 03:00 UTC if pg_cron extension is enabled.
-- Uncomment this block after enabling pg_cron in Supabase:
-- Dashboard → Database → Extensions → pg_cron → Enable
/*
select cron.schedule(
    'cleanup-sensor-events-daily',
    '0 3 * * *',
    $$select public.cleanup_old_sensor_events(90)$$
);
select cron.schedule(
    'cleanup-anomaly-flags-daily',
    '10 3 * * *',
    $$select public.cleanup_old_anomaly_flags(30)$$
);
*/

-- ---------------------------------------------------------------
-- SEED DATA (idempotent)
-- ---------------------------------------------------------------
with new_patient as (
    insert into public.patient_profiles (
        id, full_name, age, gender, bmi, family_history, medical_notes, device_id
    ) values
        ('3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2'::uuid, 'Sample Patient',           38, 'female', 27.4, true,  'Prototype patient for digital twin testing',      'device-001'),
        ('a1b2c3d4-e5f6-4a5b-8c7d-9e0f1a2b3c4d'::uuid, 'John Doe (ICU Bed 04)',   62, 'male',   31.2, true,  'Post-cardiac monitoring & elevated blood pressure','device-002'),
        ('e5f6a7b8-c9d0-4e1f-2a3b-4c5d6e7f8a9b'::uuid, 'Sarah Jenkins (Ward 2B)', 45, 'female', 24.1, false, 'Routine telemetry observation',                   'device-003')
    on conflict (id) do update set updated_at = now()
    returning id
)
insert into public.twin_states (
    patient_id, latest_hr, latest_spo2, latest_temp,
    latest_bp_systolic, latest_bp_diastolic, latest_activity_level,
    rolling_avg_24h, rolling_avg_7d, risk_label, risk_confidence, anomaly_flags, status
)
select
    id, 78.0, 98.0, 36.8, 122, 80, 5.0,
    '{"hr": 78.0, "spo2": 98.0, "temp": 36.8}'::jsonb,
    '{"hr": 76.5, "spo2": 97.8, "temp": 36.7}'::jsonb,
    'low', 0.18, '[]'::jsonb, 'stable'
from new_patient
on conflict (patient_id) do nothing;

-- ---------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------
select
    t.table_name,
    count(p.policyname) as policy_count
from information_schema.tables t
left join pg_policies p on p.tablename = t.table_name and p.schemaname = 'public'
where t.table_schema = 'public'
  and t.table_name in ('patient_profiles','twin_states','sensor_events','risk_history','anomaly_flags','alerts')
group by t.table_name
order by t.table_name;
