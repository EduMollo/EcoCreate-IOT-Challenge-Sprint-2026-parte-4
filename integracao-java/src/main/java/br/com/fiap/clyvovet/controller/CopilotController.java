package br.com.fiap.clyvovet.controller;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;
import br.com.fiap.clyvovet.service.*;
import br.com.fiap.clyvovet.exception.RegraDeNegocioException;

@Controller
@RequestMapping("/pets/{petId}/copilot")
public class CopilotController {
    private final CopilotService copilot;
    private final PetService pets;
    public CopilotController(CopilotService copilot,PetService pets) {this.copilot=copilot;this.pets=pets;}
    @GetMapping
    public String painel(@PathVariable Long petId,Model model) {
        model.addAttribute("pet",pets.buscar(petId));
        model.addAttribute("insights",copilot.historico(petId));
        model.addAttribute("configurado",copilot.configurado());
        model.addAttribute("leituras",copilot.leiturasRecentes(petId));
        return "pet/copilot";
    }
    @PostMapping("/analisar")
    public String analisar(@PathVariable Long petId,RedirectAttributes flash) {
        try {copilot.analisar(petId);flash.addFlashAttribute("mensagemSucesso","Análise registrada para revisão.");}
        catch(RegraDeNegocioException e) {flash.addFlashAttribute("mensagemErro",e.getMessage());}
        return "redirect:/pets/"+petId+"/copilot";
    }
    @PostMapping("/simular")
    public String simular(@PathVariable Long petId,@RequestParam String cenario,RedirectAttributes flash) {
        copilot.simular(petId,cenario);flash.addFlashAttribute("mensagemSucesso","Janela de sensores simulados registrada. Solicite a análise.");
        return "redirect:/pets/"+petId+"/copilot";
    }
    @PostMapping("/{id}/aprovar")
    public String aprovar(@PathVariable Long petId,@PathVariable String id,RedirectAttributes flash) {
        copilot.aprovar(petId,id);flash.addFlashAttribute("mensagemSucesso","Mensagem aprovada e disponibilizada no portal do tutor.");
        return "redirect:/pets/"+petId+"/copilot";
    }
    @PostMapping("/{id}/ler")
    public String ler(@PathVariable Long petId,@PathVariable String id,RedirectAttributes flash) {
        copilot.registrarLeitura(petId,id);flash.addFlashAttribute("mensagemSucesso","Leitura confirmada.");
        return "redirect:/pets/"+petId+"/copilot";
    }
}
