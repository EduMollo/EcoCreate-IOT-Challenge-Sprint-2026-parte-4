package br.com.fiap.clyvovet.service;

import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;
import br.com.fiap.clyvovet.model.*;
import br.com.fiap.clyvovet.model.enums.Especie;
import br.com.fiap.clyvovet.repository.*;
import br.com.fiap.clyvovet.security.UsuarioLogadoProvider;
import br.com.fiap.clyvovet.exception.RegraDeNegocioException;

@Service
public class CopilotService {
    private final PetService pets;
    private final ConsultaRepository consultas;
    private final VacinaRepository vacinas;
    private final MedicamentoRepository medicamentos;
    private final UsuarioLogadoProvider usuario;
    private final JdbcTemplate jdbc;
    private final ObjectMapper json = new ObjectMapper();
    private final CopilotGateway gateway;
    private final String url, token;
    private final TransactionTemplate transactions;

    public CopilotService(PetService pets, ConsultaRepository consultas, VacinaRepository vacinas,
            MedicamentoRepository medicamentos, UsuarioLogadoProvider usuario, JdbcTemplate jdbc, PlatformTransactionManager manager, CopilotGateway gateway,
            @Value("${copilot.url:}") String url, @Value("${copilot.token:}") String token) {
        this.pets=pets; this.consultas=consultas; this.vacinas=vacinas; this.medicamentos=medicamentos;
        this.usuario=usuario; this.jdbc=jdbc; this.url=url; this.token=token;
        this.transactions=new TransactionTemplate(manager);
        this.gateway=gateway;
    }

    public boolean configurado() { return !url.isBlank() && !token.isBlank(); }

    @Transactional(readOnly=true)
    @SuppressWarnings("unchecked")
    public List<Map<String,Object>> leiturasRecentes(Long petId) {
        pets.buscar(petId);
        List<String> windows=jdbc.query("select leituras from cv4_copilot_window where id_pet=? order by criado_em desc",
            (rs,n)->rs.getString(1),petId);
        if(windows.isEmpty()) return List.of();
        List<Map<String,Object>> rows=json.readValue(windows.get(0),List.class);
        return rows.subList(Math.max(0,rows.size()-10),rows.size());
    }
    private void exigirEquipe() {
        if (!usuario.exigir().isEquipeClinica()) throw new AccessDeniedException("Apenas equipe clínica.");
    }

    @SuppressWarnings("unchecked")
    private Map<String,Object> decode(String value) { return json.readValue(value, Map.class); }

    @Transactional(readOnly=true)
    public List<Map<String,Object>> historico(Long petId) {
        pets.buscar(petId);
        boolean equipe=usuario.exigir().isEquipeClinica();
        return jdbc.query("select id, resultado, aprovado_por, aprovado_em from cv4_copilot_insight where id_pet=? order by criado_em desc",
            (rs,n) -> {
                Map<String,Object> item=new LinkedHashMap<>();
                item.put("id",rs.getString("id"));
                boolean aprovado=rs.getString("aprovado_por")!=null;
                item.put("aprovado",aprovado);
                item.put("aprovadoPor",rs.getString("aprovado_por"));
                item.put("aprovadoEm",rs.getString("aprovado_em"));
                if (equipe) item.put("resultado",decode(rs.getString("resultado")));
                else if (aprovado) {
                    Map<String,Object> full=decode(rs.getString("resultado"));
                    item.put("resultado",Map.of("tutor_message",full.get("tutor_message"),
                        "simulated",full.get("simulated"),"ts",full.get("ts"),"llm_mode",full.get("llm_mode")));
                }
                return item;
            },petId).stream().filter(x -> equipe || Boolean.TRUE.equals(x.get("aprovado"))).limit(20).toList();
    }

    @Transactional
    public void simular(Long petId,String cenario) {
        exigirEquipe(); Pet pet=pets.buscar(petId); exigirEspecie(pet);
        if (!Set.of("normal","fever","hypoxia","lethargy","cold_start").contains(cenario))
            throw new RegraDeNegocioException("Cenário inválido.");
        List<Map<String,Object>> rows=new ArrayList<>();
        int count=cenario.equals("cold_start")?5:40;
        Instant now=Instant.now().minusSeconds(1);
        Random random=new Random(42+petId);
        for(int i=0;i<count;i++) {
            double drift=i<30?0:(i-29)/10.0;
            rows.add(Map.of("ts",now.minusSeconds((count-1-i)*60L).toString(),
                "temperature_c",(pet.getEspecie()==Especie.GATO?38.8:38.5)+random.nextGaussian()*0.07+(cenario.equals("fever")?drift*2:0),
                "heart_rate_bpm",(pet.getEspecie()==Especie.GATO?160:90)+random.nextGaussian()*2,
                "spo2_pct",97.5+random.nextGaussian()*0.2-(cenario.equals("hypoxia")?drift*9:0),
                "activity_score",Math.max(0,0.5+random.nextGaussian()*0.02-(cenario.equals("lethargy")?drift*0.45:0))));
        }
        // A simulation is one versioned window, never mixed into another scenario's baseline.
        jdbc.update("insert into cv4_copilot_window(id,id_pet,criado_em,cenario,leituras) values(?,?,?,?,?)",
            UUID.randomUUID().toString(),petId,Instant.now().toString(),cenario,json.writeValueAsString(rows));
    }

    private void exigirEspecie(Pet pet) {
        if(pet.getEspecie()!=Especie.CACHORRO && pet.getEspecie()!=Especie.GATO)
            throw new RegraDeNegocioException("O modelo desta sprint atende cães e gatos.");
    }

    @Transactional(readOnly=true)
    public Map<String,Object> contexto(Long petId) {
        exigirEquipe(); Pet p=pets.buscar(petId); exigirEspecie(p);
        Map<String,Object> pet=new LinkedHashMap<>();
        pet.put("id",p.getId()); pet.put("name",p.getNome()); pet.put("species",p.getEspecie()==Especie.GATO?"cat":"dog");
        pet.put("breed",p.getRaca()); pet.put("birth_date",p.getDataNascimento().toString());
        pet.put("weight_kg",p.getPesoKg()); pet.put("sex",p.getSexo()==null?"":p.getSexo().name());
        pet.put("neutered",Boolean.TRUE.equals(p.getCastrado()));
        // No phone, email, address or full tutor identity is sent to external generation providers.
        pet.put("tutor_name","Tutor");
        List<String> windows=jdbc.query("select leituras from cv4_copilot_window where id_pet=? order by criado_em desc",
            (rs,n)->rs.getString(1),petId);
        List<?> readings=windows.isEmpty()?List.of():json.readValue(windows.get(0),List.class);
        List<Map<String,Object>> cs=consultas.findByPetIdOrderByDataConsultaDescIdDesc(petId).stream()
            .filter(Consulta::isConcluida).map(c -> {
                Map<String,Object> m=new LinkedHashMap<>(); m.put("id",c.getId());m.put("date",c.getDataConsulta().toString());
                m.put("reason",c.getTipoConsulta().name());m.put("return_due",c.getDataRetorno()==null?null:c.getDataRetorno().toString());
                m.put("returned",consultas.findByPetIdOrderByDataConsultaDescIdDesc(petId).stream()
                    .anyMatch(r->r.isConcluida() && r.getDataConsulta().isAfter(c.getDataConsulta())));return m;
            }).toList();
        var vs=vacinas.findByPetIdOrderByDataAplicacaoDesc(petId).stream().map(v->{
            Map<String,Object> m=new LinkedHashMap<>();m.put("vaccine",v.getNome());m.put("applied_at",v.getDataAplicacao().toString());
            m.put("next_due",v.getProximaDose()==null?null:v.getProximaDose().toString());return m;
        }).toList();
        var ms=medicamentos.findByPetIdOrderByDataInicioDesc(petId).stream().map(m->{
            Map<String,Object> v=new LinkedHashMap<>();v.put("id",m.getId());v.put("name",m.getNome());
            v.put("start_date",m.getDataInicio().toString());v.put("end_date",m.getDataFim()==null?null:m.getDataFim().toString());
            // Dose adherence is unknown in the existing application; never invent confirmations.
            v.put("doses_expected",0);v.put("doses_confirmed",0);return v;
        }).toList();
        var events=jdbc.query("select tipo,criado_em from cv4_copilot_event where id_tutor=? order by criado_em desc",
            (rs,n)->Map.of("event_type",rs.getString(1),"ts",rs.getString(2),"channel","portal"),p.getTutor().getId()).stream().limit(500).toList();
        return Map.of("pet",pet,"readings",readings,"vaccines",vs,"consultations",cs,"medications",ms,"events",events,"simulated",true);
    }

    public void analisar(Long petId) {
        Map<String,Object> payload=transactions.execute(status -> contexto(petId));
        if(!configurado()) throw new RegraDeNegocioException("Serviço de IA ainda não configurado. Defina COPILOT_URL e COPILOT_TOKEN.");
        try {
            String response=gateway.analisar(url,token,json.writeValueAsString(payload));
            var result=decode(response);
            if(!String.valueOf(petId).equals(String.valueOf(result.get("pet_id"))) || !result.containsKey("risk") || !result.containsKey("tutor_message"))
                throw new IllegalStateException("Invalid response");
            jdbc.update("insert into cv4_copilot_insight(id,id_pet,criado_em,resultado,contexto) values(?,?,?,?,?)",
                UUID.randomUUID().toString(),petId,Instant.now().toString(),response,json.writeValueAsString(payload));
        } catch(InterruptedException e) {
            Thread.currentThread().interrupt(); throw new RegraDeNegocioException("Análise interrompida. Tente novamente.");
        } catch(Exception e) {
            throw new RegraDeNegocioException("Não foi possível concluir a análise. Os dados anteriores foram preservados. Verifique o serviço de IA.");
        }
    }

    @Transactional
    public void aprovar(Long petId,String id) {
        exigirEquipe(); Pet pet=pets.buscar(petId);
        int updated=jdbc.update("update cv4_copilot_insight set aprovado_por=?,aprovado_em=? where id=? and id_pet=? and aprovado_por is null",
            usuario.exigir().getUsername(),Instant.now().toString(),id,petId);
        if(updated!=1) throw new RegraDeNegocioException("Análise inexistente ou já aprovada.");
        evento(pet,id,"message_sent");
    }

    @Transactional
    public void registrarLeitura(Long petId,String id) {
        Pet pet=pets.buscar(petId);
        if(!usuario.exigir().isTutor()) throw new AccessDeniedException("Apenas o tutor confirma a leitura.");
        Integer count=jdbc.queryForObject("select count(*) from cv4_copilot_insight where id=? and id_pet=? and aprovado_por is not null",Integer.class,id,petId);
        if(count==null || count!=1) throw new RegraDeNegocioException("Mensagem não disponível.");
        Integer duplicate=jdbc.queryForObject("select count(*) from cv4_copilot_event where id_insight=? and tipo='opened'",Integer.class,id);
        if(duplicate!=null && duplicate==0) evento(pet,id,"opened");
    }

    private void evento(Pet pet,String insight,String tipo) {
        jdbc.update("insert into cv4_copilot_event(id,id_insight,id_tutor,tipo,criado_em) values(?,?,?,?,?)",
            UUID.randomUUID().toString(),insight,pet.getTutor().getId(),tipo,Instant.now().toString());
    }
}
