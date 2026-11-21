-- =============================================================================
-- 0013 — Preço consultado ao vivo na seguradora (API) pode virar solicitação
-- A opção da Azos não tem tabela de tarifa: o preço vem da API na hora. Para o cliente
-- poder contratar, a cotação grava um item apontando para um produto "de API"
-- (produto_versao em RASCUNHO, sem coberturas, tarifa_versao com fonte 'API').
-- Sem coberturas, o comparador de tabela nunca o carrega; RASCUNHO + fonte 'API' nunca
-- chega a PUBLICADO (a trava de publicação exige tarifa SEGURADORA).
-- Só relaxa a lista de fontes. Para desfazer:
--   ALTER TABLE tarifa_versao DROP CONSTRAINT fonte_tarifa_valida;
--   ALTER TABLE tarifa_versao ADD CONSTRAINT fonte_tarifa_valida
--     CHECK (fonte_tarifa IN ('FICTICIA','SEGURADORA'));
-- (antes, apague os registros com fonte 'API')
-- =============================================================================

BEGIN;

ALTER TABLE tarifa_versao DROP CONSTRAINT fonte_tarifa_valida;
ALTER TABLE tarifa_versao
  ADD CONSTRAINT fonte_tarifa_valida CHECK (fonte_tarifa IN ('FICTICIA','SEGURADORA','API'));

COMMIT;
