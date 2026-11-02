package br.com.fiap.clyvovet.config;

import static br.com.fiap.clyvovet.model.enums.PerfilEnum.ADMIN;
import static br.com.fiap.clyvovet.model.enums.PerfilEnum.TUTOR;
import static br.com.fiap.clyvovet.model.enums.PerfilEnum.VETERINARIO;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;

import jakarta.servlet.DispatcherType;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

	private static final String[] ROTAS_PUBLICAS = { "/login", "/cadastro", "/css/**", "/js/**", "/img/**", "/h2-console/**" };
	private static final String[] ROTAS_LEITURA_PET = { "/pets/{id:\\d+}", "/pets/{id:\\d+}/dashboard",
			"/pets/{id:\\d+}/historico", "/pets/{id:\\d+}/copilot" };

	@Bean
	public SecurityFilterChain filtrar(HttpSecurity http) throws Exception {
		http.authorizeHttpRequests(requests -> requests
				.dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
				.requestMatchers(ROTAS_PUBLICAS).permitAll()
				.requestMatchers("/usuarios/**", "/clinicas/**", "/relatorios/**").hasAuthority(ADMIN.name())
				.requestMatchers("/meus-pets/**").hasAuthority(TUTOR.name())
				.requestMatchers(HttpMethod.GET, ROTAS_LEITURA_PET).authenticated()
				.requestMatchers(HttpMethod.POST, "/pets/{petId:\\d+}/copilot/{id}/ler").hasAuthority(TUTOR.name())
				.requestMatchers("/pets/**", "/tutores/**", "/consultas/**")
						.hasAnyAuthority(ADMIN.name(), VETERINARIO.name())
				.anyRequest().authenticated())

			.csrf(csrf -> csrf.ignoringRequestMatchers("/h2-console/**"))
			.headers(headers -> headers.frameOptions(frame -> frame.sameOrigin()))

			.formLogin(login -> login
				.loginPage("/login")
				.defaultSuccessUrl("/", true)
				.failureUrl("/login?falha=true")
				.permitAll())
			.logout(logout -> logout
				.logoutUrl("/logout")
				.logoutSuccessUrl("/login?logout=true")
				.permitAll())
			.exceptionHandling(excecoes -> excecoes
				.accessDeniedHandler((request, response, excecao) -> response.sendRedirect("/acesso-negado")));

		return http.build();
	}

	@Bean
	public PasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder();
	}

}
