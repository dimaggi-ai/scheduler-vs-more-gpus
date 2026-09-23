CREATE TABLE IF NOT EXISTS artifacts (
    id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL CHECK(kind IN ('plan','actual')),
    plan_id VARCHAR NOT NULL, payload VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    plan_id VARCHAR NOT NULL, hour INTEGER NOT NULL,
    nominal_gpu_h DOUBLE NOT NULL, envelope_gpu_h DOUBLE NOT NULL,
    inf_alloc_gpu_h DOUBLE NOT NULL, inf_productive_gpu_h DOUBLE NOT NULL,
    inf_demand_gpu_h DOUBLE NOT NULL, train_alloc_gpu_h DOUBLE NOT NULL,
    train_productive_gpu_h DOUBLE NOT NULL, work_lost_gpu_h DOUBLE NOT NULL,
    rate_usd_per_allocated_gpu_h DOUBLE NOT NULL,
    PRIMARY KEY(plan_id, hour)
);
CREATE TABLE IF NOT EXISTS actuals (
    actual_id VARCHAR NOT NULL, plan_id VARCHAR NOT NULL, hour INTEGER NOT NULL,
    nominal_gpu_h DOUBLE NOT NULL, envelope_gpu_h DOUBLE NOT NULL,
    inf_alloc_gpu_h DOUBLE NOT NULL, inf_productive_gpu_h DOUBLE NOT NULL,
    inf_demand_gpu_h DOUBLE NOT NULL, train_alloc_gpu_h DOUBLE NOT NULL,
    train_productive_gpu_h DOUBLE NOT NULL, work_lost_gpu_h DOUBLE NOT NULL,
    rate_usd_per_allocated_gpu_h DOUBLE NOT NULL,
    PRIMARY KEY(actual_id, hour)
);
