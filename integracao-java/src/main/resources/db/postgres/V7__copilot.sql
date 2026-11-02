create table cv4_copilot_window (
 id varchar(36) primary key, id_pet bigint not null references tb_pet(id),
 criado_em varchar(40) not null, cenario varchar(30) not null, leituras text not null
);
create index ix_copilot_window_pet on cv4_copilot_window(id_pet,criado_em);
create table cv4_copilot_insight (
 id varchar(36) primary key, id_pet bigint not null references tb_pet(id),
 criado_em varchar(40) not null, resultado text not null, contexto text not null,
 aprovado_por varchar(60), aprovado_em varchar(40)
);
create index ix_copilot_insight_pet on cv4_copilot_insight(id_pet,criado_em);
create table cv4_copilot_event (
 id varchar(36) primary key, id_insight varchar(36) not null references cv4_copilot_insight(id),
 id_tutor bigint not null references tb_tutor(id), tipo varchar(30) not null, criado_em varchar(40) not null,
 constraint uq_copilot_event unique(id_insight,tipo)
);
