#include "tree_sitter/parser.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum TokenType {
    COLON_DASH,
    COLON,
    DASH,
};

typedef enum {
    START,
    COLON_SEEN,
} State;

typedef enum {
    CONTINUE,
    RETURN_TOKEN,
    FAIL,
} Action;

#define EXECUTE(action) do{\
    Action result = (action);\
    if (result == RETURN_TOKEN) {\
        printf("*** Returning token: %d\n", lexer->result_symbol);\
        return true;\
    } else if (result == FAIL) {\
        return false;\
    }\
} while(0); continue

static inline void advance(TSLexer *lexer) { lexer->advance(lexer, false); }

static inline void skip(TSLexer *lexer) { lexer->advance(lexer, true); }

static inline void skip_blanks(TSLexer *lexer) {
    while (!lexer->eof(lexer) && (lexer->lookahead == ' ' || lexer->lookahead == '\t' || lexer->lookahead == '\n' || lexer->lookahead == '\r' || lexer->lookahead == '\f')) {
        skip(lexer);
    }
}

static inline Action state_start(TSLexer *lexer, const bool *valid_symbols, State *state) {
    skip_blanks(lexer);
    switch (lexer->lookahead){
    case ':':
        *state = COLON_SEEN;
        advance(lexer);
        return CONTINUE;
    case '-':
        if (valid_symbols[DASH]) {
            lexer->result_symbol = DASH;
            advance(lexer);
            return RETURN_TOKEN;
        }
        return FAIL;
    }
    return FAIL;
}

static inline Action state_colon_seen(TSLexer *lexer, const bool *valid_symbols, State *state) {
    switch (lexer->lookahead){
    case '-':
        if (valid_symbols[COLON_DASH]) {
            lexer->result_symbol = COLON_DASH;
            advance(lexer);
            return RETURN_TOKEN;
        }
        return FAIL;
    default:
        if (valid_symbols[COLON]) {
            lexer->result_symbol = COLON;
            return RETURN_TOKEN;
        }
        return FAIL;
    }
}

bool tree_sitter_clingo_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
    // printf("*** External scanner invoked. Valid: %d %d %d\n", valid_symbols[COLON_DASH], valid_symbols[COLON], valid_symbols[DASH]);
    State state = START;
    for(;;){
        // printf("*** Lookahead: '%c' State: %d\n", lexer->lookahead, state);
        if (lexer->eof(lexer)) return false;
        switch (state)
        {
        case START:
            EXECUTE(state_start(lexer, valid_symbols, &state));
            break;
        case COLON_SEEN:
            EXECUTE(state_colon_seen(lexer, valid_symbols, &state));
            break;
        default:
            break;
        }
    }
    return false;
}

unsigned tree_sitter_clingo_external_scanner_serialize(void *payload, char *buffer) {
    return 0;
}

void tree_sitter_clingo_external_scanner_deserialize(void *payload, const char *buffer, unsigned length) {
    return;
}

void *tree_sitter_clingo_external_scanner_create() {
     printf("External scanner created\n");
    return NULL;
}

void tree_sitter_clingo_external_scanner_destroy(void *payload) {
    return;
}
