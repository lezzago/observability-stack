ARG OPENSEARCH_DOCKER_REPO
ARG OPENSEARCH_VERSION
FROM ${OPENSEARCH_DOCKER_REPO}/opensearch:${OPENSEARCH_VERSION}

# Replace the bundled SQL plugin with a locally built version
ARG SQL_PLUGIN_ZIP=opensearch-sql-3.6.0.0-SNAPSHOT.zip

# Remove the existing SQL plugin (suppress errors if not found)
RUN /usr/share/opensearch/bin/opensearch-plugin remove opensearch-sql --purge || true

# Copy and install the local build
COPY --chown=opensearch:opensearch ${SQL_PLUGIN_ZIP} /tmp/${SQL_PLUGIN_ZIP}
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch file:///tmp/${SQL_PLUGIN_ZIP} \
    && rm /tmp/${SQL_PLUGIN_ZIP}
