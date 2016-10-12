package 'apache2'

bag = data_bag_item('data', 'local')
web_docroot = bag['web_docroot']

directory File.join(web_docroot, 'oa-runone') do
  owner bag['username']
  mode '0755'
end

hostname = Socket.gethostbyname(Socket.gethostname).first

file '/etc/apache2/sites-available/worker.conf' do
  content <<-CONF
<VirtualHost *:80>
    ServerName #{hostname}
    DocumentRoot #{web_docroot}
    ErrorLog ${APACHE_LOG_DIR}/worker-error.log
    CustomLog ${APACHE_LOG_DIR}/worker-access.log combined
</VirtualHost>
CONF
end

execute 'a2ensite worker'
execute 'a2dissite 000-default'

execute 'service apache2 reload'
