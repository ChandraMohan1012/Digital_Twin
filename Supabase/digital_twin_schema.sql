-- Digital Twin Database Schema for Supabase
-- Paste this entire script into the Supabase SQL Editor and run it.

create extension if not exists "uuid-ossp";

-- 1) Patient profile table
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

-- 2) Current digital twin state
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
    rolling_avg_24h jsonb not null default '{}'::jsonb,
    rolling_avg_7d jsonb not null default '{}'::jsonb,
    risk_label text not null default 'low',
    risk_confidence numeric(5,2) not null default 0.00,
    anomaly_flags jsonb not null default '[]'::jsonb,
    status text not null default 'stable',
    unique(patient_id)
);

-- 3) Raw sensor readings received from wearable/app
create table if not exists public.sensor_events (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    source text not null default 'wearable',
    payload jsonb not null,
    created_at timestamptz not null default now()
);

-- 4) Risk score history over time
create table if not exists public.risk_history (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    recorded_at timestamptz not null default now(),
    risk_label text not null,
    risk_confidence numeric(5,2) not null default 0.00,
    shap_top_features jsonb not null default '{}'::jsonb
);

-- 5) Anomaly flags detected from sensor patterns
create table if not exists public.anomaly_flags (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    flag_type text not null,
    severity text not null default 'medium',
    description text,
    detected_at timestamptz not null default now(),
    resolved boolean not null default false
);

-- 6) Alerts to be shown in app/dashboard
create table if not exists public.alerts (
    id uuid primary key default uuid_generate_v4(),
    patient_id uuid not null references public.patient_profiles(id) on delete cascade,
    alert_type text not null,
    severity text not null default 'medium',
    message text not null,
    is_read boolean not null default false,
    created_at timestamptz not null default now()
);

-- Indexes
create index if not exists idx_twin_states_patient_id on public.twin_states(patient_id);
create index if not exists idx_sensor_events_patient_created on public.sensor_events(patient_id, created_at desc);
create index if not exists idx_risk_history_patient_time on public.risk_history(patient_id, recorded_at desc);
create index if not exists idx_anomaly_flags_patient on public.anomaly_flags(patient_id, detected_at desc);
create index if not exists idx_alerts_patient on public.alerts(patient_id, created_at desc);

-- Updated-at trigger helper
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger set_patient_profiles_updated_at
before update on public.patient_profiles
for each row
execute function public.set_updated_at();

create trigger set_twin_states_updated_at
before update on public.twin_states
for each row
execute function public.set_updated_at();

-- Enable RLS
alter table public.patient_profiles enable row level security;
alter table public.twin_states enable row level security;
alter table public.sensor_events enable row level security;
alter table public.risk_history enable row level security;
alter table public.anomaly_flags enable row level security;
alter table public.alerts enable row level security;

-- Row-level security policies: restrict write access to Supabase service role.
-- NOTE: For production tighten these further (add per-user policies, add `auth_id` on patient_profiles).

-- patient_profiles: only service role may insert/update/delete; selects reserved for service role until app-level rules are added.
create policy "service_role_select_patient_profiles" on public.patient_profiles
for select using (auth.role() = 'service_role');
create policy "service_role_insert_patient_profiles" on public.patient_profiles
for insert with check (auth.role() = 'service_role');
create policy "service_role_update_patient_profiles" on public.patient_profiles
for update using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "service_role_delete_patient_profiles" on public.patient_profiles
for delete using (auth.role() = 'service_role');

-- twin_states: backend/service role manages writes
create policy "service_role_select_twin_states" on public.twin_states
for select using (auth.role() = 'service_role');
create policy "service_role_insert_twin_states" on public.twin_states
for insert with check (auth.role() = 'service_role');
create policy "service_role_update_twin_states" on public.twin_states
for update using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "service_role_delete_twin_states" on public.twin_states
for delete using (auth.role() = 'service_role');

-- sensor_events: allow service role to insert (ingestion path). You may permit client inserts via Edge functions or dedicated endpoints instead.
create policy "service_role_select_sensor_events" on public.sensor_events
for select using (auth.role() = 'service_role');
create policy "service_role_insert_sensor_events" on public.sensor_events
for insert with check (auth.role() = 'service_role');
create policy "service_role_update_sensor_events" on public.sensor_events
for update using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "service_role_delete_sensor_events" on public.sensor_events
for delete using (auth.role() = 'service_role');

-- risk_history: write-only for service role (backend/ML), reads also service role.
create policy "service_role_select_risk_history" on public.risk_history
for select using (auth.role() = 'service_role');
create policy "service_role_insert_risk_history" on public.risk_history
for insert with check (auth.role() = 'service_role');
create policy "service_role_update_risk_history" on public.risk_history
for update using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "service_role_delete_risk_history" on public.risk_history
for delete using (auth.role() = 'service_role');

-- anomaly_flags
create policy "service_role_select_anomaly_flags" on public.anomaly_flags
for select using (auth.role() = 'service_role');
create policy "service_role_insert_anomaly_flags" on public.anomaly_flags
for insert with check (auth.role() = 'service_role');
create policy "service_role_update_anomaly_flags" on public.anomaly_flags
for update using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "service_role_delete_anomaly_flags" on public.anomaly_flags
for delete using (auth.role() = 'service_role');

-- alerts
create policy "service_role_select_alerts" on public.alerts
for select using (auth.role() = 'service_role');
create policy "service_role_insert_alerts" on public.alerts
for insert with check (auth.role() = 'service_role');
create policy "service_role_update_alerts" on public.alerts
for update using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
create policy "service_role_delete_alerts" on public.alerts
for delete using (auth.role() = 'service_role');

-- Consider adding a `auth_id text` column to `patient_profiles` and per-user SELECT policies for authenticated users.

-- Optional sample seed data for testing
-- Trigger function: process_sensor_event
-- This computes simple rolling averages and updates/creates `twin_states`,
-- inserts a provisional `risk_history` row and emits a NOTIFY for backend ML processing.
create or replace function public.process_sensor_event()
returns trigger
language plpgsql
as $$
declare
    v_hr numeric;
    v_spo2 numeric;
    v_temp numeric;
    v_bp_systolic integer;
    v_bp_diastolic integer;
    avg_hr_24 numeric;
    avg_spo2_24 numeric;
    avg_temp_24 numeric;
    avg_hr_7d numeric;
    avg_spo2_7d numeric;
    avg_temp_7d numeric;
begin
    if (NEW.payload ? 'hr') then v_hr := (NEW.payload->>'hr')::numeric; end if;
    if (NEW.payload ? 'spo2') then v_spo2 := (NEW.payload->>'spo2')::numeric; end if;
    if (NEW.payload ? 'temp') then v_temp := (NEW.payload->>'temp')::numeric; end if;
    if (NEW.payload ? 'bp_sys') then v_bp_systolic := (NEW.payload->>'bp_sys')::integer; end if;
    if (NEW.payload ? 'bp_dia') then v_bp_diastolic := (NEW.payload->>'bp_dia')::integer; end if;

    select avg((payload->>'hr')::numeric) into avg_hr_24
    from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '24 hours';

    select avg((payload->>'spo2')::numeric) into avg_spo2_24
    from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '24 hours';

    select avg((payload->>'temp')::numeric) into avg_temp_24
    from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '24 hours';

    select avg((payload->>'hr')::numeric) into avg_hr_7d
    from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '7 days';

    select avg((payload->>'spo2')::numeric) into avg_spo2_7d
    from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '7 days';

    select avg((payload->>'temp')::numeric) into avg_temp_7d
    from public.sensor_events
    where patient_id = NEW.patient_id and created_at >= now() - interval '7 days';

    -- Try update; insert if missing
    update public.twin_states set
        latest_hr = coalesce(v_hr, latest_hr),
        latest_spo2 = coalesce(v_spo2, latest_spo2),
        latest_temp = coalesce(v_temp, latest_temp),
        latest_bp_systolic = coalesce(v_bp_systolic, latest_bp_systolic),
        latest_bp_diastolic = coalesce(v_bp_diastolic, latest_bp_diastolic),
        rolling_avg_24h = jsonb_build_object(
            'hr', round(coalesce(avg_hr_24, latest_hr::numeric)::numeric,2),
            'spo2', round(coalesce(avg_spo2_24, latest_spo2::numeric)::numeric,2),
            'temp', round(coalesce(avg_temp_24, latest_temp::numeric)::numeric,2)
        ),
        rolling_avg_7d = jsonb_build_object(
            'hr', round(coalesce(avg_hr_7d, latest_hr::numeric)::numeric,2),
            'spo2', round(coalesce(avg_spo2_7d, latest_spo2::numeric)::numeric,2),
            'temp', round(coalesce(avg_temp_7d, latest_temp::numeric)::numeric,2)
        ),
        updated_at = now()
    where patient_id = NEW.patient_id;

    if not found then
        insert into public.twin_states (
            patient_id, latest_hr, latest_spo2, latest_temp, latest_bp_systolic, latest_bp_diastolic,
            rolling_avg_24h, rolling_avg_7d, risk_label, risk_confidence, anomaly_flags, status
        ) values (
            NEW.patient_id, v_hr, v_spo2, v_temp, v_bp_systolic, v_bp_diastolic,
            jsonb_build_object('hr', avg_hr_24, 'spo2', avg_spo2_24, 'temp', avg_temp_24),
            jsonb_build_object('hr', avg_hr_7d, 'spo2', avg_spo2_7d, 'temp', avg_temp_7d),
            'pending', 0.0, '[]'::jsonb, 'unknown'
        );
    end if;

    -- Insert provisional risk row; backend ML can update it later.
    insert into public.risk_history (patient_id, risk_label, risk_confidence, shap_top_features)
    values (NEW.patient_id, 'pending', 0.0, '{}'::jsonb);

    -- Notify listeners (backend) to run model/analysis
    perform pg_notify('sensor_event_received', json_build_object('patient_id', NEW.patient_id, 'event_id', NEW.id)::text);

    return NEW;
end;
$$;

create trigger process_sensor_event_trigger
after insert on public.sensor_events
for each row
execute function public.process_sensor_event();
with new_patient as (
    insert into public.patient_profiles (
        full_name,
        age,
        gender,
        bmi,
        family_history,
        medical_notes,
        device_id
    ) values (
        'Sample Patient',
        38,
        'female',
        27.4,
        true,
        'Prototype patient for digital twin testing',
        'device-001'
    ) returning id
)
insert into public.twin_states (
    patient_id,
    latest_hr,
    latest_spo2,
    latest_temp,
    latest_bp_systolic,
    latest_bp_diastolic,
    rolling_avg_24h,
    rolling_avg_7d,
    risk_label,
    risk_confidence,
    anomaly_flags,
    status
)
select
    id,
    78.0,
    98.0,
    36.8,
    122,
    80,
    '{"hr": 78.0, "spo2": 98.0, "temp": 36.8}'::jsonb,
    '{"hr": 76.5, "spo2": 97.8, "temp": 36.7}'::jsonb,
    'low',
    0.18,
    '[]'::jsonb,
    'stable'
from new_patient;

-- Verification query
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('patient_profiles','twin_states','sensor_events','risk_history','anomaly_flags','alerts')
order by table_name;
