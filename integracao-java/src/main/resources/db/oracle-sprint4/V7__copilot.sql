create table cv4_copilot_window (
 id varchar2(36) primary key, id_pet number(19) not null references tb_pet(id),
 criado_em varchar2(40) not null, cenario varchar2(30) not null, leituras clob not null
);
create index ix_copilot_window_pet on cv4_copilot_window(id_pet,criado_em);
create table cv4_copilot_insight (
 id varchar2(36) primary key, id_pet number(19) not null references tb_pet(id),
 criado_em varchar2(40) not null, resultado clob not null, contexto clob not null,
 aprovado_por varchar2(60), aprovado_em varchar2(40)
);
create index ix_copilot_insight_pet on cv4_copilot_insight(id_pet,criado_em);
create table cv4_copilot_event (
 id varchar2(36) primary key, id_insight varchar2(36) not null references cv4_copilot_insight(id),
 id_tutor number(19) not null references tb_tutor(id), tipo varchar2(30) not null, criado_em varchar2(40) not null,
 constraint uq_copilot_event unique(id_insight,tipo)
);
